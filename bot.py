import discord
from discord import app_commands
from discord.ext import commands
import re
import json
import os
import threading
from flask import Flask

# --- WEBサーバーの設定 (Render & UptimeRobot用) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_web_server)
    t.start()
# ------------------------------------------------

# --- 設定項目 ---
TOKEN = os.environ.get("DISCORD_TOKEN")
# 💡 データを保存する専用チャンネルのIDを設定
DATA_CHANNEL_ID = 1568303101797208104
# ----------------

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("スラッシュコマンドを同期しました。")

bot = MyBot()
todo_list = []
last_msg_id = None

async def save_data():
    """データを指定されたDiscordチャンネルにメッセージとして保存する"""
    channel = bot.get_channel(DATA_CHANNEL_ID)
    if not channel:
        print("警告: データ保存用チャンネルが見つかりません。")
        return
    
    # 過去の保存ログを削除して最新のものだけにする
    async for message in channel.history(limit=10):
        if message.author == bot.user:
            try:
                await message.delete()
            except:
                pass

    data = {"todo_list": todo_list, "last_msg_id": last_msg_id}
    json_data = json.dumps(data, ensure_ascii=False, indent=4)
    
    # 2000文字を超える場合はコードブロックを分割（通常用途ならこれで十分収まります）
    await channel.send(f"```json\n{json_data}\n```")

async def load_data():
    """Discordチャンネルの最新メッセージからデータを復元する"""
    global todo_list, last_msg_id
    channel = bot.get_channel(DATA_CHANNEL_ID)
    if not channel:
        print("警告: データ読み込み用チャンネルが見つかりません。")
        return

    async for message in channel.history(limit=10):
        if message.author == bot.user and message.content.startswith("```json"):
            try:
                # ```json と ``` を取り除いてパース
                raw_content = message.content.strip("`").replace("json\n", "", 1)
                data = json.loads(raw_content)
                if isinstance(data, list):
                    todo_list = data
                    last_msg_id = None
                else:
                    todo_list = data.get("todo_list", [])
                    last_msg_id = data.get("last_msg_id")
                print("Discordからデータを正常に復元しました。")
                return
            except Exception as e:
                print(f"データ復元失敗: {e}")
    print("過去の保存データが見つかりませんでした。新規作成します。")

@bot.event
async def on_ready():
    await load_data()
    print(f'ログインしました: {bot.user.name}')

async def delete_last_message(interaction: discord.Interaction):
    global last_msg_id
    if last_msg_id:
        try:
            msg = await interaction.channel.fetch_message(last_msg_id)
            await msg.delete()
        except:
            pass

def format_date_display(date_str):
    digits = re.sub(r'\D', '', date_str)
    if len(digits) == 8:
        return f"{digits[0:4]}/{digits[4:6]}/{digits[6:8]}"
    elif len(digits) == 4:
        return f"{digits[0:2]}/{digits[2:4]}"
    return date_str

def create_todo_text():
    if not todo_list:
        return "現在、未完了のタスクはありません。☕"
    
    def sort_key(item):
        date_str = re.sub(r'\D', '', item['due'])
        return date_str.zfill(8)

    todo_list.sort(key=sort_key)
    
    text = "📝 **現在の依頼・ToDoリスト(期限順)**\n------------------\n"
    for i, item in enumerate(todo_list, 1):
        display_date = format_date_display(item['due'])
        text += f"**{i}. {item['task']}** (期限: **{display_date}**)"
        
        client = item.get('client')
        song = item.get('song')
        paid = item.get('paid', False)
        contract = item.get('contract', False)
        data_received = item.get('data_received', False)

        if client or song:
            data_emoji = ":inbox_tray:受領済" if data_received else ":x:未受領"
            contract_emoji = "📜送付済" if contract else "📄未送付"
            pay_emoji = ":white_check_mark:" if paid else ":x:"
            
            text += f"\n └ 👤: {client or '?'} / 🎵: {song or '?'}\n └ 素材: {data_emoji} / 契約: {contract_emoji} / 支払い: {pay_emoji}"
        
        text += "\n"
    return text

async def send_refresh_list(interaction: discord.Interaction, notice_text: str = ""):
    global last_msg_id
    # 💡 応答エラー対策：時間のかかる処理（削除や保存）より先に、最優先でdeferを実行して時間を確保
    await interaction.response.defer()
    
    await delete_last_message(interaction)
    full_text = f"{notice_text}\n\n{create_todo_text()}" if notice_text else create_todo_text()
    new_msg = await interaction.followup.send(full_text)
    last_msg_id = new_msg.id
    
    # 💡 データの保存処理を最後に実行
    await save_data()

# --- スラッシュコマンド ---

@bot.tree.command(name="todo", description="タスクを追加します")
async def todo(interaction: discord.Interaction, task_name: str, due_date: str, client: str = None, song: str = None, data_received: bool = False, contract: bool = False, paid: bool = False):
    new_task = {
        "task": task_name, "due": due_date, "client": client, 
        "song": song, "data_received": data_received, 
        "contract": contract, "paid": paid
    }
    todo_list.append(new_task)
    await send_refresh_list(interaction, "🆕 タスクを追加しました")

@bot.tree.command(name="data", description="指定した番号のタスクを「音源受領済み」に変更します")
async def mark_as_data(interaction: discord.Interaction, index: int):
    if 0 < index <= len(todo_list):
        todo_list[index - 1]['data_received'] = True
        await send_refresh_list(interaction, f"📥 番号 {index} の音源受領を記録しました")
    else:
        await interaction.response.send_message("番号が見つかりません。", ephemeral=True)

@bot.tree.command(name="contract", description="契約書送付済みに変更")
async def mark_as_contract(interaction: discord.Interaction, index: int):
    if 0 < index <= len(todo_list):
        todo_list[index - 1]['contract'] = True
        await send_refresh_list(interaction, f"📜 番号 {index} の契約書送付を記録")
    else:
        await interaction.response.send_message("番号が見つかりません。", ephemeral=True)

@bot.tree.command(name="paid", description="入金済みに変更")
async def mark_as_paid(interaction: discord.Interaction, index: int):
    if 0 < index <= len(todo_list):
        todo_list[index - 1]['paid'] = True
        await send_refresh_list(interaction, f"💰 番号 {index} の入金を確認")
    else:
        await interaction.response.send_message("番号が見つかりません。", ephemeral=True)

@bot.tree.command(name="edit", description="内容を修正します")
async def edit(interaction: discord.Interaction, index: int, task_name: str = None, due_date: str = None, client: str = None, song: str = None, data_received: bool = None, contract: bool = None, paid: bool = None):
    if 0 < index <= len(todo_list):
        task = todo_list[index - 1]
        if task_name: task['task'] = task_name
        if due_date: task['due'] = due_date
        if client: task['client'] = client
        if song: task['song'] = song
        if data_received is not None: task['data_received'] = data_received
        if contract is not None: task['contract'] = contract
        if paid is not None: task['paid'] = paid
        await send_refresh_list(interaction, f"✅ 番号 {index} を更新しました")
    else:
        await interaction.response.send_message("番号が見つかりません。", ephemeral=True)

@bot.tree.command(name="list", description="リストを再表示")
async def list_tasks(interaction: discord.Interaction):
    await send_refresh_list(interaction)

@bot.tree.command(name="done", description="タスクを完了して消去")
async def done(interaction: discord.Interaction, index: int):
    if 0 < index <= len(todo_list):
        removed = todo_list.pop(index - 1)
        await send_refresh_list(interaction, f"🎊 「{removed['task']}」を完了!")
    else:
        await interaction.response.send_message("番号が見つかりません。", ephemeral=True)

keep_alive()
bot.run(TOKEN)
