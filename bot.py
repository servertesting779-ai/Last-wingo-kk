# bot.py - Diablo Prediction Bot with REAL Data
import logging
import aiohttp
import sqlite3
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, JobQueue

# ==================== CONFIG ====================
TOKEN = "8723966859:AAFeTtafFUz_ySZIWyHpYLQMycVOmw-Ij4U"
API_URL = 'https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json'
BOT_USERNAME = "diablo_prediction_bot"

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== DATABASE SETUP ====================
conn = sqlite3.connect('predictions.db', check_same_thread=False)
cursor = conn.cursor()

# Create tables
cursor.execute('''
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period TEXT UNIQUE,
        prediction TEXT,
        actual_result TEXT,
        result_status TEXT,
        created_at TIMESTAMP
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        joined_at TIMESTAMP,
        last_active TIMESTAMP
    )
''')
conn.commit()

# ==================== HELPER FUNCTIONS ====================

def get_size(num):
    """Convert number to BIG/SMALL"""
    try:
        num = int(num)
        return 'BIG' if num >= 5 else 'SMALL'
    except:
        return 'SMALL'

def save_prediction(period, prediction):
    """Save prediction to database"""
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO predictions (period, prediction, created_at)
            VALUES (?, ?, ?)
        ''', (period, prediction, datetime.now()))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Save error: {e}")
        return False

def update_result(period, actual):
    """Update prediction with actual result"""
    try:
        cursor.execute('SELECT prediction FROM predictions WHERE period = ?', (period,))
        result = cursor.fetchone()
        
        if result:
            prediction = result[0]
            status = 'WIN' if prediction == actual else 'LOSS'
            
            cursor.execute('''
                UPDATE predictions 
                SET actual_result = ?, result_status = ?
                WHERE period = ?
            ''', (actual, status, period))
            conn.commit()
            return status
    except Exception as e:
        logger.error(f"Update error: {e}")
    return None

def get_last_prediction():
    """Get most recent prediction"""
    cursor.execute('''
        SELECT period, prediction, actual_result, result_status 
        FROM predictions 
        ORDER BY created_at DESC LIMIT 1
    ''')
    return cursor.fetchone()

def get_recent_predictions(limit=5):
    """Get recent predictions with results"""
    cursor.execute('''
        SELECT period, prediction, actual_result, result_status 
        FROM predictions 
        WHERE actual_result IS NOT NULL
        ORDER BY created_at DESC LIMIT ?
    ''', (limit,))
    return cursor.fetchall()

def get_stats():
    """Get win/loss statistics"""
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN result_status = 'WIN' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result_status = 'LOSS' THEN 1 ELSE 0 END) as losses
        FROM predictions 
        WHERE result_status IS NOT NULL
    ''')
    return cursor.fetchone()

def add_user(user_id, username, first_name):
    """Add user to database"""
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, joined_at, last_active)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, datetime.now(), datetime.now()))
        conn.commit()
    except:
        pass

def update_user_activity(user_id):
    """Update user last active time"""
    try:
        cursor.execute('UPDATE users SET last_active = ? WHERE user_id = ?', 
                      (datetime.now(), user_id))
        conn.commit()
    except:
        pass

# ==================== API FUNCTIONS ====================

async def fetch_data():
    """Fetch data from API"""
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"{API_URL}?t={int(datetime.now().timestamp())}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('data', {}).get('list', [])
                else:
                    logger.error(f"API status: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"API error: {e}")
        return []

async def update_data():
    """Update predictions and results"""
    try:
        data = await fetch_data()
        if not data:
            return None
        
        # Process results (update actual results)
        for item in data[:10]:
            try:
                period = item.get('issueNumber')
                number = item.get('number')
                if number:
                    actual = get_size(number)
                    update_result(period, actual)
            except:
                continue
        
        # Generate new prediction for next period
        if data and len(data) > 0:
            latest = data[0].get('issueNumber')
            try:
                if 'M' in latest:
                    # Format: 202503061054M
                    base = latest[:-1]
                    num = int(latest[-2:-1]) if latest[-2:-1].isdigit() else 0
                    next_period = f"{base}{num + 1}M"
                else:
                    next_period = str(int(latest) + 1)
            except:
                next_period = f"{int(latest) + 1}"
            
            # Check if prediction exists
            cursor.execute('SELECT period FROM predictions WHERE period = ?', (next_period,))
            exists = cursor.fetchone()
            
            if not exists:
                # Simple prediction logic
                results = []
                for item in data[:5]:
                    num = item.get('number')
                    if num:
                        results.append(get_size(num))
                
                if len(results) >= 3:
                    if results[0] == results[1] == results[2]:
                        prediction = 'SMALL' if results[0] == 'BIG' else 'BIG'
                    elif results[0] != results[1] and results[1] != results[2]:
                        prediction = 'SMALL' if results[2] == 'BIG' else 'BIG'
                    else:
                        big_count = results.count('BIG')
                        prediction = 'SMALL' if big_count >= 3 else 'BIG'
                else:
                    prediction = 'BIG'
                
                save_prediction(next_period, prediction)
                return next_period, prediction
        
        return None
    except Exception as e:
        logger.error(f"Update error: {e}")
        return None

# ==================== BACKGROUND TASK ====================

async def background_task():
    """Run in background"""
    while True:
        try:
            await update_data()
            await asyncio.sleep(10)  # Update every 10 seconds
        except:
            await asyncio.sleep(10)

# ==================== BOT COMMANDS ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    update_user_activity(user.id)
    
    # Get stats
    total, wins, losses = get_stats() or (0, 0, 0)
    win_rate = (wins / total * 100) if total > 0 else 0
    
    welcome_msg = (
        f"🎯 *DIABLO REAL PREDICTION BOT*\n\n"
        f"Welcome {user.first_name}! 🤖\n\n"
        f"*📊 BOT STATS:*\n"
        f"Total Predictions: {total}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"📈 Win Rate: {win_rate:.1f}%\n\n"
        f"*Commands:*\n"
        f"🔮 /predict - Latest prediction\n"
        f"📜 /history - Last 5 results\n"
        f"📊 /stats - Bot statistics\n"
        f"🔄 /latest - Latest period result\n"
        f"❓ /help - Show help"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("🔮 Predict", callback_data="predict"),
            InlineKeyboardButton("📜 History", callback_data="history")
        ],
        [
            InlineKeyboardButton("📊 Stats", callback_data="stats"),
            InlineKeyboardButton("🔄 Latest", callback_data="latest")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_msg, 
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    help_text = (
        "🤖 *COMMANDS*\n\n"
        "/start - Start bot\n"
        "/predict - Get latest prediction\n"
        "/history - Last 5 results\n"
        "/stats - Bot statistics\n"
        "/latest - Latest period result\n"
        "/help - Show help\n\n"
        "✅ *Bot Status:* ONLINE"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get latest prediction"""
    user = update.effective_user
    update_user_activity(user.id)
    
    await update.message.reply_text("🔮 *Fetching latest prediction...*", parse_mode='Markdown')
    
    # Force update
    result = await update_data()
    
    # Get last prediction
    last = get_last_prediction()
    
    if last:
        period, prediction, actual, status = last
        
        msg = (
            f"🎯 *LATEST PREDICTION*\n\n"
            f"📌 Period: `{period}`\n"
            f"🔮 Prediction: *{prediction}*\n"
        )
        
        if actual:
            icon = "✅" if status == "WIN" else "❌"
            msg += f"\n📊 Result: {icon} {actual} ({status})"
        else:
            msg += f"\n⏳ Status: Waiting for result..."
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("⏳ No prediction yet. Please wait...")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show prediction history"""
    user = update.effective_user
    update_user_activity(user.id)
    
    predictions = get_recent_predictions(5)
    
    if not predictions:
        await update.message.reply_text("📜 No history available yet.")
        return
    
    msg = "📜 *LAST 5 RESULTS*\n\n"
    
    for i, (period, pred, actual, status) in enumerate(predictions, 1):
        icon = "✅" if status == "WIN" else "❌"
        msg += f"{i}. Period: `{period[-8:]}`\n"
        msg += f"   {pred} → {icon} {actual} ({status})\n\n"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    user = update.effective_user
    update_user_activity(user.id)
    
    total, wins, losses = get_stats() or (0, 0, 0)
    win_rate = (wins / total * 100) if total > 0 else 0
    
    msg = (
        f"📊 *BOT STATISTICS*\n\n"
        f"Total Predictions: {total}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"📈 Win Rate: {win_rate:.1f}%\n"
    )
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get latest period result"""
    user = update.effective_user
    update_user_activity(user.id)
    
    # Get the most recent completed prediction
    cursor.execute('''
        SELECT period, prediction, actual_result, result_status 
        FROM predictions 
        WHERE actual_result IS NOT NULL
        ORDER BY created_at DESC LIMIT 1
    ''')
    
    last = cursor.fetchone()
    
    if last:
        period, pred, actual, status = last
        icon = "✅" if status == "WIN" else "❌"
        
        msg = (
            f"🔄 *LATEST RESULT*\n\n"
            f"📌 Period: `{period}`\n"
            f"🔮 Prediction: {pred}\n"
            f"🎲 Actual: {actual}\n"
            f"📈 Result: {icon} {status}"
        )
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text("⏳ No results yet.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    update_user_activity(user.id)
    
    if query.data == "predict":
        await predict_command(update, context)
    elif query.data == "history":
        await history_command(update, context)
    elif query.data == "stats":
        await stats_command(update, context)
    elif query.data == "latest":
        await latest_command(update, context)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An error occurred. Please try again."
        )

# ==================== MAIN FUNCTION ====================

async def startup_task(app):
    """Task to run when bot starts"""
    asyncio.create_task(background_task())

def main():
    """Start the bot"""
    print("=" * 60)
    print("🤖 DIABLO REAL PREDICTION BOT v2.0")
    print("=" * 60)
    print(f"📱 Bot Token: {TOKEN[:10]}...{TOKEN[-5:]}")
    print(f"📢 Bot Username: @{BOT_USERNAME}")
    print(f"🌐 API URL: {API_URL}")
    print("=" * 60)
    
    # Create application
    app = Application.builder().token(TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("predict", predict_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("latest", latest_command))
    
    # Add button handler
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    app.add_error_handler(error_handler)
    
    # Run startup task
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(background_task())
    
    print("\n✅ Bot is running with REAL DATA! Press Ctrl+C to stop.\n")
    print("📊 Fetching real periods and win/loss history...")
    
    # Start bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
