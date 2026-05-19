import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite
import json
import os
import io
import os
import logging
import asyncio
from datetime import datetime, timedelta

# ==========================================
# إعداد نظام اللوغ
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("CookiesBot")

# ==========================================
# توكن البوت
# ==========================================

from dotenv import load_dotenv

# تحميل ملف الـ .env ليقرأ التوكن فوراً
load_dotenv()

# قراءة التوكن بشكل آمن وتخزينه في المتغير
TOKEN = os.getenv("DISCORD_TOKEN")
# ==========================================
# الكلاس الرئيسي للبوت
# ==========================================
class CookiesStudioBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        self.DB_PATH = 'studio_system.db'
        self.COMMANDS_CHANNEL_ID = 1504491870129094707
        self.ADMIN_LOG_CHANNEL_ID = 1504899260746043482
        self.BACKUP_CHANNEL_ID = 1504899483274575985
        self._booking_locks = {}

    def get_booking_lock(self, work_name: str, chapter_num: int, role: str) -> asyncio.Lock:
        key = f"{work_name}:{chapter_num}:{role}"
        if key not in self._booking_locks:
            self._booking_locks[key] = asyncio.Lock()
        return self._booking_locks[key]

    async def setup_hook(self):
        async with aiosqlite.connect(self.DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")

            await db.execute('''CREATE TABLE IF NOT EXISTS works (
                name TEXT PRIMARY KEY,
                current_chapter INTEGER,
                is_active INTEGER DEFAULT 1,
                max_hours INTEGER DEFAULT 24,
                required_roles INTEGER DEFAULT 3)''')

            await db.execute('''CREATE TABLE IF NOT EXISTS reservations (
                user_id INTEGER,
                user_name TEXT,
                work_name TEXT,
                chapter_num INTEGER,
                role TEXT,
                time_booked TEXT,
                last_reminded TEXT,
                last_reminder_msg_id INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                submission_link1 TEXT,
                submission_link2 TEXT,
                submission_attempts INTEGER DEFAULT 0,
                submission_deadline TEXT)''')

            await db.execute('''CREATE TABLE IF NOT EXISTS members_profile (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                balance REAL DEFAULT 0.0,
                warnings INTEGER DEFAULT 0,
                completed_chapters INTEGER DEFAULT 0,
                max_slots INTEGER DEFAULT 3,
                is_excluded INTEGER DEFAULT 0,
                excluded_balance_snapshot REAL DEFAULT 0.0)''')

            await db.execute('''CREATE TABLE IF NOT EXISTS drive_links (
                work_name TEXT,
                chapter_num INTEGER,
                role TEXT,
                drive_url1 TEXT,
                drive_url2 TEXT,
                drive_url3 TEXT,
                drive_url4 TEXT,
                is_booked INTEGER DEFAULT 0,
                is_frozen INTEGER DEFAULT 0,
                PRIMARY KEY (work_name, chapter_num, role))''')

            await db.execute('''CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT)''')

            await db.execute('''CREATE TABLE IF NOT EXISTS roles_config (
                role_name TEXT PRIMARY KEY,
                price REAL,
                is_enabled INTEGER DEFAULT 1)''')

            await db.execute('''CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_name TEXT,
                command_name TEXT,
                details TEXT,
                timestamp TEXT)''')

            await db.execute('''CREATE TABLE IF NOT EXISTS chapter_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_name TEXT,
                work_name TEXT,
                chapter_num INTEGER,
                role TEXT,
                link1 TEXT,
                link2 TEXT,
                status TEXT DEFAULT 'pending_review',
                reject_reason TEXT,
                attempts INTEGER DEFAULT 0,
                submitted_at TEXT,
                reviewed_at TEXT,
                review_msg_id INTEGER DEFAULT 0)''')

            await db.execute('''CREATE TABLE IF NOT EXISTS custom_commands (
                command_name TEXT PRIMARY KEY,
                response_text TEXT,
                created_by TEXT,
                created_at TEXT)''')

            # إنشاء الفهارس لتسريع الاستعلامات
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_reservations_user
                ON reservations(user_id)''')
            await db.execute('''CREATE INDEX IF NOT EXISTS idx_reservations_work
                ON reservations(work_name, chapter_num, role)''')

            defaults = [
                ('commands_channel', str(self.COMMANDS_CHANNEL_ID)),
                ('admin_log_channel', str(self.ADMIN_LOG_CHANNEL_ID)),
                ('backup_channel', str(self.BACKUP_CHANNEL_ID)),
                ('pay_day_notice', 'غير محدد'),
                ('submission_deadline_hours', '6'),
                ('max_edit_attempts', '2'),
            ]
            for key, value in defaults:
                await db.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value)
                )

            default_roles = [
                ("المحرر", 0.50, 1),
                ("المترجم الكوري", 0.50, 1),
                ("المبيض", 0.25, 1),
                ("المترجم الإنجليزي", 0.25, 1),
            ]
            for r_name, r_price, r_status in default_roles:
                await db.execute(
                    "INSERT OR IGNORE INTO roles_config (role_name, price, is_enabled) VALUES (?, ?, ?)",
                    (r_name, r_price, r_status)
                )

            await db.commit()

            # ==========================================
            # ترقية قاعدة البيانات — إضافة الأعمدة الناقصة تلقائياً
            # ==========================================
            migrations = [
                # members_profile
                ("ALTER TABLE members_profile ADD COLUMN is_excluded INTEGER DEFAULT 0", "members_profile.is_excluded"),
                ("ALTER TABLE members_profile ADD COLUMN excluded_balance_snapshot REAL DEFAULT 0.0", "members_profile.excluded_balance_snapshot"),
                ("ALTER TABLE members_profile ADD COLUMN max_slots INTEGER DEFAULT 3", "members_profile.max_slots"),
                # reservations
                ("ALTER TABLE reservations ADD COLUMN last_reminded TEXT DEFAULT ''", "reservations.last_reminded"),
                ("ALTER TABLE reservations ADD COLUMN last_reminder_msg_id INTEGER DEFAULT 0", "reservations.last_reminder_msg_id"),
                ("ALTER TABLE reservations ADD COLUMN status TEXT DEFAULT 'pending'", "reservations.status"),
                ("ALTER TABLE reservations ADD COLUMN submission_link1 TEXT", "reservations.submission_link1"),
                ("ALTER TABLE reservations ADD COLUMN submission_link2 TEXT", "reservations.submission_link2"),
                ("ALTER TABLE reservations ADD COLUMN submission_attempts INTEGER DEFAULT 0", "reservations.submission_attempts"),
                ("ALTER TABLE reservations ADD COLUMN submission_deadline TEXT", "reservations.submission_deadline"),
                # works
                ("ALTER TABLE works ADD COLUMN max_hours INTEGER DEFAULT 24", "works.max_hours"),
                ("ALTER TABLE works ADD COLUMN required_roles INTEGER DEFAULT 3", "works.required_roles"),
                # drive_links
                ("ALTER TABLE drive_links ADD COLUMN is_booked INTEGER DEFAULT 0", "drive_links.is_booked"),
                ("ALTER TABLE drive_links ADD COLUMN is_frozen INTEGER DEFAULT 0", "drive_links.is_frozen"),
            ]
            for sql, col_name in migrations:
                try:
                    await db.execute(sql)
                    logger.info(f"✅ تم إضافة عمود: {col_name}")
                except Exception:
                    pass  # العمود موجود مسبقاً

            # تأكد من تحديث last_reminded الفارغة
            await db.execute(
                "UPDATE reservations SET last_reminded=time_booked WHERE last_reminded IS NULL OR last_reminded=''"
            )
            await db.commit()
            logger.info("✅ تم التحقق من هيكل قاعدة البيانات وترقيتها.")

        await self.load_live_settings()
        self.check_deadlines_and_reminders.start()
        self.auto_backup_every_3_hours.start()
        self.tree.interaction_check = self.global_channel_check
        await self.tree.sync()

    async def load_live_settings(self):
        async with aiosqlite.connect(self.DB_PATH) as db:
            async with db.execute("SELECT key, value FROM settings") as cursor:
                rows = await cursor.fetchall()
                for key, value in rows:
                    if key == 'commands_channel':
                        self.COMMANDS_CHANNEL_ID = int(value)
                    elif key == 'admin_log_channel':
                        self.ADMIN_LOG_CHANNEL_ID = int(value)
                    elif key == 'backup_channel':
                        self.BACKUP_CHANNEL_ID = int(value)

    async def on_ready(self):
        logger.info(f"🤖 البوت {self.user.name} يعمل الآن!")
        logger.info(f"📁 روم العمليات: {self.COMMANDS_CHANNEL_ID}")
        logger.info(f"🚨 روم السجل الإداري: {self.ADMIN_LOG_CHANNEL_ID}")
        logger.info(f"📦 روم الباك أب: {self.BACKUP_CHANNEL_ID}")
        await self.send_welcome_embed_once()
        await self.register_custom_commands_on_startup()

    async def register_custom_commands_on_startup(self):
        async with aiosqlite.connect(self.DB_PATH) as db:
            async with db.execute("SELECT command_name, response_text FROM custom_commands") as cursor:
                rows = await cursor.fetchall()

        for cmd_name, response_text in rows:
            await self._register_single_custom_command(cmd_name, response_text)

        if rows:
            await self.tree.sync()
            logger.info(f"✅ تم تسجيل {len(rows)} أمر مخصص عند بدء التشغيل.")

    async def _register_single_custom_command(self, cmd_name: str, response_text: str):
        captured_response = response_text

        @self.tree.command(name=cmd_name, description=f"أمر مخصص: {cmd_name}")
        async def dynamic_cmd(interaction: discord.Interaction):
            embed = discord.Embed(
                title=f"📢 {cmd_name}",
                description=captured_response,
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)

    async def log_admin_action(self, admin_name: str, command_name: str, details: str):
        async with aiosqlite.connect(self.DB_PATH) as db:
            await db.execute(
                "INSERT INTO admin_logs (admin_name, command_name, details, timestamp) VALUES (?, ?, ?, ?)",
                (admin_name, command_name, details, datetime.now().isoformat())
            )
            await db.execute("""
                DELETE FROM admin_logs
                WHERE id NOT IN (
                    SELECT id FROM admin_logs ORDER BY id DESC LIMIT 50
                )
            """)
            await db.commit()

    async def send_welcome_embed_once(self):
        """ترسل الكليشه مرة واحدة فقط في قناة الأوامر — تتحقق من DB"""
        async with aiosqlite.connect(self.DB_PATH) as db:
            async with db.execute("SELECT value FROM settings WHERE key='welcome_sent'") as cursor:
                sent = await cursor.fetchone()

            if sent:
                # سبق وأُرسلت، لا ترسل مجدداً
                return

            channel = self.get_channel(self.COMMANDS_CHANNEL_ID)
            if not channel:
                try:
                    channel = await self.fetch_channel(self.COMMANDS_CHANNEL_ID)
                except Exception as e:
                    logger.error(f"خطأ جلب قناة الترحيب: {e}")
                    return

            async with db.execute(
                "SELECT role_name, price FROM roles_config WHERE is_enabled=1"
            ) as r_cur:
                roles_data = await r_cur.fetchall()

            roles_text = ""
            for r_name, r_price in roles_data:
                roles_text += f"• **{r_name}**: `+{r_price:.2f}$` لكل فصل منجز.\n"

            embed = discord.Embed(
                title="🍪 دليل نظام الحجز والإنتاج الآلي المطور | تيم كوكيز",
                color=discord.Color.gold()
            )
            embed.description = (
                "مرحباً بكم جميعاً يا أبطال في نظام أتمتة حجوزات فصول المانهوا المطور بالكامل لقسم مانهوا أزورا.\n\n"
                f"### 📑 تفاصيل التخصصات والمكافآت المعتمدة حالياً:\n{roles_text}\n"
                "### 📥 كيف تبدأ بحجز الفصول؟\n"
                "1️⃣ قم بكتابة أمر `/حجز_عمل` داخل هذا الشات المخصص للعمليات.\n"
                "2️⃣ اختر اسم العمل والتخصص، وسيقوم البوت بإرسال روابط مجلدات الدرايف لخاصك فوراً.\n"
                "3️⃣ بمجرد انتهائك، اكتب أمر `/تم_اكتمال_عمل` لرفع رابط العمل وإغلاق الحجز.\n\n"
                "### ⚠️ مهلة العمل والجزاءات التلقائية:\n"
                "• مدة العمل الافتراضية على أي فصل هي **24 ساعة فقط**.\n"
                "• سيرسل البوت تذكيرات دورية كل ساعتين.\n"
                "• في حال تجاوز المهلة أو الانسحاب، يُسحب الحجز آلياً ويُسجل إنذار رسمي وعقوبة خصم مالي.\n"
                "• تراكم 3 إنذارات يسبب حظر الحساب تلقائياً."
            )
            if self.user.avatar:
                embed.set_thumbnail(url=self.user.avatar.url)
            embed.set_footer(text="لوحة تحكم وتوجيه طاقم تيم كوكيز الآلية")

            try:
                await channel.send(content="@everyone", embed=embed)
                await db.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES ('welcome_sent', 'true')"
                )
                await db.commit()
                logger.info("✅ تم إرسال رسالة الترحيب.")
            except Exception as e:
                logger.error(f"خطأ رسالة الترحيب: {e}")

    async def get_admin_log_channel(self):
        """جلب قناة السجل الإداري بشكل موثوق"""
        channel = self.get_channel(self.ADMIN_LOG_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.fetch_channel(self.ADMIN_LOG_CHANNEL_ID)
            except Exception as e:
                logger.error(f"❌ فشل جلب قناة السجل الإداري: {e}")
                return None
        return channel

    async def send_admin_log(self, embed: discord.Embed):
        """إرسال موثوق لقناة السجل الإداري"""
        try:
            channel = await self.get_admin_log_channel()
            if channel:
                await channel.send(embed=embed)
            else:
                logger.error(f"❌ قناة السجل الإداري غير متاحة: {self.ADMIN_LOG_CHANNEL_ID}")
        except discord.Forbidden:
            logger.error(f"❌ البوت ليس لديه صلاحية الإرسال في قناة السجل الإداري")
        except Exception as e:
            logger.error(f"خطأ سجل الإدارة: {e}")

    async def notify_admin_member_action(self, member: discord.Member, action_title: str, details: str, color: discord.Color = discord.Color.blue()):
        embed = discord.Embed(
            title=f"🔔 إشعار عضو | {action_title}",
            color=color,
            timestamp=datetime.now()
        )
        embed.description = details
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"معرف العضو: {member.id}")
        await self.send_admin_log(embed)

    async def global_channel_check(self, interaction: discord.Interaction) -> bool:
        # السماح دائماً للمشرفين
        if interaction.user.guild_permissions.administrator:
            return True
        # السماح بالتفاعلات مع المكونات (أزرار وقوائم) في أي مكان
        if interaction.type == discord.InteractionType.component:
            return True
        # باقي الأوامر فقط في قناة الأوامر
        if interaction.channel_id == self.COMMANDS_CHANNEL_ID:
            return True
        raise app_commands.AppCommandError(
            f"❌ الأوامر مقفلة هنا. توجه إلى الروم المخصص: <#{self.COMMANDS_CHANNEL_ID}>"
        )

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        # السماح بالرسائل في الخاص (DM) للبوت
        if isinstance(message.channel, discord.DMChannel):
            await self.process_commands(message)
            return
        if message.channel.id == self.COMMANDS_CHANNEL_ID:
            if not message.author.guild_permissions.administrator:
                if not message.content.startswith("/"):
                    try:
                        await message.delete()
                        warn_msg = await message.channel.send(
                            f"⚠️ {message.author.mention} **عذراً! تم حذف رسالتك لأن هذا الشات مخصص للأوامر فقط.**"
                        )
                        await asyncio.sleep(5)
                        await warn_msg.delete()
                    except Exception:
                        pass
                    return
        await self.process_commands(message)

    async def check_chapter_completion(self, work_name: str, chapter_num: int):
        """تحقق منفصل من اكتمال الفصل بـ connection خاص به"""
        async with aiosqlite.connect(self.DB_PATH) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            async with db.execute(
                "SELECT required_roles FROM works WHERE name=?", (work_name,)
            ) as cursor:
                row = await cursor.fetchone()
            required = row[0] if row else 3

            async with db.execute("""
                SELECT COUNT(*) FROM chapter_submissions
                WHERE work_name=? AND chapter_num=? AND status='approved'
            """, (work_name, chapter_num)) as cursor:
                approved_count = (await cursor.fetchone())[0]

            if approved_count >= required:
                await db.execute(
                    "UPDATE works SET current_chapter = current_chapter + 1 WHERE name=?",
                    (work_name,)
                )
                async with db.execute(
                    "SELECT current_chapter FROM works WHERE name=?", (work_name,)
                ) as cursor:
                    new_chap_row = await cursor.fetchone()
                new_chapter = new_chap_row[0] if new_chap_row else chapter_num + 1
                await db.commit()

                log_embed = discord.Embed(
                    title="📈 تحديث تلقائي لعداد فصول المانهوا",
                    color=discord.Color.gold()
                )
                log_embed.description = (
                    f"• **العمل:** `{work_name}`\n"
                    f"• **الفصل المكتمل:** {chapter_num} (اكتملت {approved_count}/{required} تخصصات)\n"
                    f"• **العداد الجديد:** الفصل **{new_chapter}**"
                )
                await self.send_admin_log(log_embed)

                commands_channel = self.get_channel(self.COMMANDS_CHANNEL_ID)
                if commands_channel:
                    complete_embed = discord.Embed(
                        title="🎉 اكتمل فصل جديد!",
                        color=discord.Color.green()
                    )
                    complete_embed.description = (
                        f"✅ تم اكتمال **جميع تخصصات** مانهوا:\n"
                        f"📚 **{work_name}** | الفصل **{chapter_num}**\n\n"
                        f"🚀 العمل انتقل الآن إلى الفصل **{new_chapter}**"
                    )
                    try:
                        await commands_channel.send(embed=complete_embed)
                    except Exception:
                        pass
                return True
        return False

    @tasks.loop(minutes=10)
    async def check_deadlines_and_reminders(self):
        await self.wait_until_ready()
        try:
            async with aiosqlite.connect(self.DB_PATH) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                async with db.execute("""
                    SELECT r.user_id, r.user_name, r.work_name, r.chapter_num, r.role,
                           r.time_booked, r.last_reminded, r.last_reminder_msg_id,
                           COALESCE(w.max_hours, 24), r.submission_deadline, r.status
                    FROM reservations r
                    LEFT JOIN works w ON r.work_name = w.name
                """) as cursor:
                    all_res = await cursor.fetchall()

                now = datetime.now()

                for (uid, uname, work, chap, role, booked_str, last_rem_str,
                     last_msg_id, max_hours, sub_deadline_str, status) in all_res:

                    booked_time = datetime.fromisoformat(booked_str)
                    last_reminded_time = datetime.fromisoformat(last_rem_str)
                    elapsed_total = now - booked_time
                    elapsed_since_reminder = now - last_reminded_time

                    # انتهاء مهلة رفع الروابط
                    if status == 'awaiting_submission' and sub_deadline_str:
                        sub_deadline = datetime.fromisoformat(sub_deadline_str)
                        if now > sub_deadline:
                            await db.execute(
                                "DELETE FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                                (uid, work, chap, role)
                            )
                            await db.execute(
                                "UPDATE drive_links SET is_booked=0, is_frozen=0 WHERE work_name=? AND chapter_num=? AND role=?",
                                (work, chap, role)
                            )
                            async with db.execute(
                                "SELECT price FROM roles_config WHERE role_name=?", (role,)
                            ) as rc_cur:
                                rc_row = await rc_cur.fetchone()
                            role_price = rc_row[0] if rc_row else 0.25
                            penalty_fee = round(role_price * 0.1, 2)

                            async with db.execute(
                                "SELECT balance, warnings FROM members_profile WHERE user_id=?", (uid,)
                            ) as p_cur:
                                p_data = await p_cur.fetchone()

                            if p_data:
                                await db.execute(
                                    "UPDATE members_profile SET balance=?, warnings=? WHERE user_id=?",
                                    (p_data[0] - penalty_fee, p_data[1] + 1, uid)
                                )
                            await db.commit()

                            try:
                                member = await self.fetch_user(uid)
                                if member:
                                    dm_embed = discord.Embed(
                                        title="⏰ انتهت مهلة رفع روابط الفصل",
                                        color=discord.Color.red()
                                    )
                                    dm_embed.description = (
                                        f"انتهت مهلة رفع روابط الفصل لـ مانهوا `{work}` فصل `{chap}` تخصص `{role}`.\n"
                                        f"تم إلغاء حجزك وتسجيل خصم `{penalty_fee}$` من محفظتك."
                                    )
                                    await member.send(embed=dm_embed)
                            except Exception:
                                pass

                            log_embed = discord.Embed(
                                title="⏰ انتهاء مهلة رفع الروابط (تلقائي)",
                                color=discord.Color.red()
                            )
                            log_embed.description = (
                                f"• **العضو:** <@{uid}> (`{uname}`)\n"
                                f"• **العمل:** `{work}` (فصل {chap}) تخصص `{role}`\n"
                                f"• **الجزاء:** خصم `{penalty_fee}$` وإنذار تلقائي"
                            )
                            await self.send_admin_log(log_embed)
                            continue

                    # تجاوز مهلة العمل الأصلية
                    if elapsed_total >= timedelta(hours=max_hours) and status == 'pending':
                        try:
                            await db.execute(
                                "DELETE FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                                (uid, work, chap, role)
                            )
                            await db.execute(
                                "UPDATE drive_links SET is_booked=0 WHERE work_name=? AND chapter_num=? AND role=?",
                                (work, chap, role)
                            )
                            async with db.execute(
                                "SELECT price FROM roles_config WHERE role_name=?", (role,)
                            ) as rc_cur2:
                                rc_row2 = await rc_cur2.fetchone()
                            role_price2 = rc_row2[0] if rc_row2 else 0.25
                            penalty_fee = round(role_price2 * 0.1, 2)

                            async with db.execute(
                                "SELECT balance, warnings, max_slots FROM members_profile WHERE user_id=?", (uid,)
                            ) as p_cur:
                                p_data = await p_cur.fetchone()

                            if p_data:
                                await db.execute(
                                    "UPDATE members_profile SET balance=?, warnings=?, max_slots=? WHERE user_id=?",
                                    (p_data[0] - penalty_fee, p_data[1] + 1, max(3, p_data[2] - 1), uid)
                                )
                            await db.commit()
                        except Exception as e:
                            logger.error(f"خطأ في سحب الحجز التلقائي: {e}")
                            continue

                        log_embed = discord.Embed(
                            title=f"⏰ سحب تلقائي لتجاوز الوقت ({max_hours} ساعة)",
                            color=discord.Color.red()
                        )
                        log_embed.description = (
                            f"• **العضو:** <@{uid}> (`{uname}`)\n"
                            f"• **العمل:** `{work}` (فصل {chap}) تخصص `{role}`\n"
                            f"• **الجزاء:** إنذار + خصم `{penalty_fee}$`"
                        )
                        await self.send_admin_log(log_embed)

                        if last_msg_id and last_msg_id > 0:
                            try:
                                chan = self.get_channel(self.COMMANDS_CHANNEL_ID)
                                if chan:
                                    m = await chan.fetch_message(last_msg_id)
                                    await m.delete()
                            except Exception:
                                pass
                        continue

                    # حذف رسالة التذكير القديمة بعد ساعة
                    if (last_msg_id and last_msg_id > 0
                            and timedelta(hours=1) <= elapsed_since_reminder < timedelta(hours=2)):
                        try:
                            chan = self.get_channel(self.COMMANDS_CHANNEL_ID)
                            if chan:
                                m = await chan.fetch_message(last_msg_id)
                                await m.delete()
                            await db.execute(
                                "UPDATE reservations SET last_reminder_msg_id=0 WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                                (uid, work, chap, role)
                            )
                            await db.commit()
                        except Exception:
                            pass

                    # إرسال تذكير دوري كل ساعتين
                    if (elapsed_since_reminder >= timedelta(hours=2)
                            and (not last_msg_id or last_msg_id == 0)
                            and status == 'pending'):
                        chan = self.get_channel(self.COMMANDS_CHANNEL_ID)
                        if chan:
                            hours_left = max_hours - int(elapsed_total.total_seconds() / 3600)
                            if hours_left <= 4:
                                rem_embed = discord.Embed(
                                    title="⚠️ تنبيه أخير وصارم",
                                    color=discord.Color.red()
                                )
                                rem_embed.description = (
                                    f"🔔 <@{uid}>، متبقي لك **{hours_left} ساعات فقط** لتسليم مانهوا "
                                    f"`{work}` فصل `{chap}` تخصص ({role})!"
                                )
                            else:
                                rem_embed = discord.Embed(
                                    title="⏱️ تذكير دوري",
                                    color=discord.Color.orange()
                                )
                                rem_embed.description = (
                                    f"• <@{uid}> تعمل على: `{work}` (فصل {chap}) تخصص `{role}`\n"
                                    f"• الوقت المتبقي: **{hours_left} ساعة**"
                                )

                            try:
                                new_msg = await chan.send(content=f"<@{uid}>", embed=rem_embed)
                                await db.execute(
                                    "UPDATE reservations SET last_reminded=?, last_reminder_msg_id=? WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                                    (now.isoformat(), new_msg.id, uid, work, chap, role)
                                )
                                await db.commit()
                            except Exception:
                                pass

        except Exception as e:
            logger.error(f"خطأ في check_deadlines_and_reminders: {e}")

    @tasks.loop(hours=3)
    async def auto_backup_every_3_hours(self):
        await self.wait_until_ready()
        channel = self.get_channel(self.BACKUP_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.fetch_channel(self.BACKUP_CHANNEL_ID)
            except Exception:
                return

        try:
            async with aiosqlite.connect(self.DB_PATH) as db:
                async with db.execute(
                    "SELECT user_id, user_name, balance, completed_chapters, warnings FROM members_profile"
                ) as cursor:
                    profiles = await cursor.fetchall()
                async with db.execute(
                    "SELECT user_id, work_name, chapter_num, role, time_booked FROM reservations"
                ) as cursor:
                    reservations = await cursor.fetchall()
                # جلب أسعار التخصصات الفعلية
                async with db.execute(
                    "SELECT role_name, price FROM roles_config"
                ) as cursor:
                    roles_prices = {r[0]: r[1] for r in await cursor.fetchall()}

            backup_data = {}
            for uid, uname, balance, completed, warnings in profiles:
                user_key = str(uid)
                backup_data[user_key] = []
                user_res = [r for r in reservations if r[0] == uid]

                if user_res:
                    for _, work, chap, role, b_time in user_res:
                        actual_price = roles_prices.get(role, 0.25)
                        backup_data[user_key].append({
                            "اسم_العمل": work,
                            "الفصل": str(chap),
                            "التخصص": role,
                            "المبلغ": actual_price,
                            "الملاحظات": "حجز نشط معلق",
                            "التوقيت": b_time,
                            "اسم_المستخدم": uname,
                            "أضيف_بواسطة": str(self.user.id)
                        })
                else:
                    backup_data[user_key].append({
                        "اسم_العمل": "نظام المكافآت والخصومات",
                        "الفصل": "رصيد تراكمي صافي",
                        "التخصص": "ملخص البروفايل",
                        "المبلغ": balance,
                        "الملاحظات": f"إنذارات نشطة: {warnings} | فصول مكتملة: {completed}",
                        "التوقيت": datetime.now().isoformat(),
                        "اسم_المستخدم": uname,
                        "أضيف_بواسطة": str(self.user.id)
                    })

            json_string = json.dumps(backup_data, ensure_ascii=False, indent=2)
            file_stream = io.BytesIO(json_string.encode('utf-8'))
            discord_file = discord.File(
                fp=file_stream,
                filename=f"نسخة_احتياطية_{datetime.now().strftime('%Y-%m-%d_%H-%M')}.json"
            )

            embed = discord.Embed(
                title="📦 نسخة احتياطية تلقائية (كل 3 ساعات)",
                color=discord.Color.purple(),
                timestamp=datetime.now()
            )
            embed.description = "تم إنشاء ملف الـ JSON الشامل لكافة البيانات تلقائياً."
            await channel.send(embed=embed, file=discord_file)
        except Exception as e:
            logger.error(f"خطأ في النسخ الاحتياطي: {e}")


bot = CookiesStudioBot()


# ==========================================
# دالة مساعدة: جلب أو إنشاء ملف العضو
# ==========================================
async def get_or_create_profile(db, user_id: int, user_name: str) -> dict:
    async with db.execute(
        "SELECT balance, warnings, completed_chapters, max_slots, is_excluded, excluded_balance_snapshot FROM members_profile WHERE user_id=?",
        (user_id,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        await db.execute(
            "INSERT INTO members_profile (user_id, user_name, balance, warnings, completed_chapters, max_slots, is_excluded, excluded_balance_snapshot) VALUES (?, ?, 0.0, 0, 0, 3, 0, 0.0)",
            (user_id, user_name)
        )
        await db.commit()
        return {"balance": 0.0, "warnings": 0, "completed": 0, "slots": 3, "is_excluded": 0, "excluded_snapshot": 0.0}
    else:
        await db.execute(
            "UPDATE members_profile SET user_name=? WHERE user_id=?",
            (user_name, user_id)
        )
        return {
            "balance": row[0],
            "warnings": row[1],
            "completed": row[2],
            "slots": row[3],
            "is_excluded": row[4],
            "excluded_snapshot": row[5]
        }


async def get_profile_standalone(user_id: int, user_name: str) -> dict:
    async with aiosqlite.connect(bot.DB_PATH) as db:
        return await get_or_create_profile(db, user_id, user_name)


# ==========================================
# Autocomplete helpers
# ==========================================
async def autocomplete_works(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT name FROM works WHERE is_active=1 ORDER BY name ASC"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        app_commands.Choice(name=row[0], value=row[0])
        for row in rows
        if current.lower() in row[0].lower()
    ][:25]


async def autocomplete_all_works(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT name FROM works ORDER BY name ASC"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        app_commands.Choice(name=row[0], value=row[0])
        for row in rows
        if current.lower() in row[0].lower()
    ][:25]


async def autocomplete_roles(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT role_name FROM roles_config WHERE is_enabled=1"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        app_commands.Choice(name=row[0], value=row[0])
        for row in rows
        if current.lower() in row[0].lower()
    ][:25]


async def autocomplete_all_roles(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT role_name FROM roles_config"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        app_commands.Choice(name=row[0], value=row[0])
        for row in rows
        if current.lower() in row[0].lower()
    ][:25]


async def autocomplete_custom_commands(interaction: discord.Interaction, current: str):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT command_name FROM custom_commands ORDER BY command_name ASC"
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        app_commands.Choice(name=row[0], value=row[0])
        for row in rows
        if current.lower() in row[0].lower()
    ][:25]


# ==========================================
# 🟢 نظام الحجز المطور
# ==========================================

class DirectBookLauncher(discord.ui.View):
    def __init__(self, author, target_member=None, original_msg_id=None):
        super().__init__(timeout=60)
        self.author = author
        self.target_member = target_member if target_member else author
        self.original_msg_id = original_msg_id

    @discord.ui.button(label="🟢 تأكيد ومتابعة الحجز", style=discord.ButtonStyle.success)
    async def confirm_launch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ هذا الأمر لا يخصك!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT name, current_chapter FROM works WHERE is_active=1 ORDER BY name ASC"
            ) as cursor:
                all_works = await cursor.fetchall()

        if not all_works:
            await interaction.followup.send(
                content="📭 لا توجد أعمال نشطة متاحة للحجز حالياً.",
                ephemeral=True
            )
            return

        chunks = [all_works[i:i + 24] for i in range(0, len(all_works), 24)]
        view = WorkPaginationView(chunks, self.author, self.target_member, self.original_msg_id)
        await interaction.followup.send(
            content=f"⬇️ **اختر اسم المانهوا للعضو ({self.target_member.display_name}):**",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="🔴 إلغاء الطلب", style=discord.ButtonStyle.danger)
    async def cancel_launch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ هذا الأمر لا يخصك!", ephemeral=True)
            return
        try:
            chan = bot.get_channel(bot.COMMANDS_CHANNEL_ID)
            if chan:
                m = await chan.fetch_message(interaction.message.id)
                await m.delete()
        except Exception:
            pass
        await interaction.response.send_message("❌ **تم إلغاء الطلب.**", ephemeral=True)


class WorkPaginationView(discord.ui.View):
    def __init__(self, chunks, author, target_member, original_msg_id):
        super().__init__(timeout=60)
        self.chunks = chunks
        self.author = author
        self.target_member = target_member
        self.original_msg_id = original_msg_id
        self.current_page = 0
        self.add_select()

    def add_select(self):
        self.clear_items()
        current_works = self.chunks[self.current_page]
        options = [
            discord.SelectOption(
                label=w[0],
                description=f"الفصل الحالي: {w[1]}",
                value=f"{w[0]}|{w[1]}"
            )
            for w in current_works
        ]
        select_menu = discord.ui.Select(
            placeholder=f"➡️ اختر المانهوا (صفحة {self.current_page + 1}/{len(self.chunks)})...",
            options=options
        )
        select_menu.callback = self.select_callback
        self.add_item(select_menu)

        if len(self.chunks) > 1:
            prev_btn = discord.ui.Button(
                label="◀️ السابق",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page == 0)
            )
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(
                label="▶️ التالي",
                style=discord.ButtonStyle.secondary,
                disabled=(self.current_page == len(self.chunks) - 1)
            )
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    async def select_callback(self, interaction: discord.Interaction):
        work_name, chapter_num = interaction.data['values'][0].split("|")

        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT role_name, price FROM roles_config WHERE is_enabled=1"
            ) as cursor:
                enabled_roles = await cursor.fetchall()

        if not enabled_roles:
            await interaction.response.edit_message(
                content="❌ لا توجد تخصصات مفعّلة حالياً.",
                view=None
            )
            return

        view = discord.ui.View()
        view.add_item(
            InteractiveRoleSelect(
                work_name, int(chapter_num),
                self.author, self.target_member,
                self.original_msg_id, enabled_roles
            )
        )
        await interaction.response.edit_message(
            content=f"🟢 تم اختيار مانهوا: **{work_name}**\n👇 حدد التخصص الإنتاجي:",
            view=view
        )

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        self.add_select()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        self.add_select()
        await interaction.response.edit_message(view=self)


class InteractiveRoleSelect(discord.ui.Select):
    def __init__(self, work_name, chapter_num, author, target_member, original_msg_id, enabled_roles):
        self.work_name = work_name
        self.chapter_num = chapter_num
        self.author = author
        self.target_member = target_member
        self.original_msg_id = original_msg_id
        options = [
            discord.SelectOption(label=r[0], value=r[0], description=f"المكافأة: {r[1]:.2f}$")
            for r in enabled_roles
        ]
        super().__init__(placeholder="🎭 اختر تخصص العمل...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        selected_role = self.values[0]

        lock = bot.get_booking_lock(self.work_name, self.chapter_num, selected_role)
        async with lock:
            async with aiosqlite.connect(bot.DB_PATH) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                profile = await get_or_create_profile(db, self.target_member.id, self.target_member.display_name)

                if profile["is_excluded"] == 1:
                    await interaction.followup.send(
                        content="🚫 **مرفوض:** هذا الحساب مستبعد حالياً ولا يمكنه الحجز.",
                        ephemeral=True
                    )
                    return

                if profile["warnings"] >= 3:
                    await interaction.followup.send(
                        content="🚫 **مرفوض:** هذا الحساب محظور لتجاوز حد الـ 3 إنذارات.",
                        ephemeral=True
                    )
                    return

                async with db.execute(
                    "SELECT COUNT(*) FROM reservations WHERE user_id=?", (self.target_member.id,)
                ) as cursor:
                    current_slots = (await cursor.fetchone())[0]

                if current_slots >= profile["slots"]:
                    await interaction.followup.send(
                        content=f"❌ **مرفوض:** استنفد العضو كامل سعة حجوزاته ({profile['slots']}).",
                        ephemeral=True
                    )
                    return

                async with db.execute(
                    "SELECT is_frozen FROM drive_links WHERE work_name=? AND chapter_num=? AND role=?",
                    (self.work_name, self.chapter_num, selected_role)
                ) as cursor:
                    frozen_row = await cursor.fetchone()

                if frozen_row and frozen_row[0] == 1:
                    await interaction.followup.send(
                        content=f"❌ **مرفوض:** تخصص `{selected_role}` مجمد في هذا الفصل (تم قبوله مسبقاً).",
                        ephemeral=True
                    )
                    return

                try:
                    async with db.execute("""
                        SELECT chapter_num, drive_url1, drive_url2, drive_url3, drive_url4
                        FROM drive_links
                        WHERE work_name=? AND role=? AND is_booked=0 AND is_frozen=0
                        ORDER BY chapter_num ASC LIMIT 1
                    """, (self.work_name, selected_role)) as cursor:
                        batch_data = await cursor.fetchone()

                    if not batch_data:
                        async with db.execute(
                            "SELECT drive_url1, drive_url2, drive_url3, drive_url4 FROM drive_links WHERE work_name=? AND chapter_num=? AND role=? AND is_frozen=0",
                            (self.work_name, self.chapter_num, selected_role)
                        ) as cursor:
                            link_data_row = await cursor.fetchone()
                        assigned_chap = self.chapter_num
                        link_data = link_data_row if link_data_row else None
                    else:
                        assigned_chap = batch_data[0]
                        link_data = batch_data[1:5]

                    if not link_data or not any(link_data):
                        await interaction.followup.send(
                            content=f"❌ لا توجد فصول أو روابط متاحة للتخصص `{selected_role}` في مانهوا `{self.work_name}`.",
                            ephemeral=True
                        )
                        return

                    async with db.execute(
                        "SELECT user_id FROM reservations WHERE work_name=? AND chapter_num=? AND role=?",
                        (self.work_name, assigned_chap, selected_role)
                    ) as cursor:
                        already_booked = await cursor.fetchone()

                    if already_booked:
                        await interaction.followup.send(
                            content=f"❌ **مرفوض:** تم حجز هذا الفصل والتخصص من قِبَل عضو آخر للتو.",
                            ephemeral=True
                        )
                        return

                    await db.execute(
                        """INSERT INTO reservations
                        (user_id, user_name, work_name, chapter_num, role, time_booked, last_reminded, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                        (self.target_member.id, self.target_member.display_name,
                         self.work_name, assigned_chap, selected_role,
                         datetime.now().isoformat(), datetime.now().isoformat())
                    )
                    await db.execute(
                        "UPDATE drive_links SET is_booked=1 WHERE work_name=? AND chapter_num=? AND role=?",
                        (self.work_name, assigned_chap, selected_role)
                    )
                    await db.commit()

                except Exception as e:
                    logger.error(f"خطأ في الحجز: {e}")
                    await interaction.followup.send(
                        content="❌ حدث خطأ أثناء الحجز، يرجى المحاولة مرة أخرى.",
                        ephemeral=True
                    )
                    return

        links_text = ""
        for i, url in enumerate(link_data, 1):
            if url:
                links_text += f"\n🔗 **رابط المجلد {i}:** {url}"

        try:
            dm_embed = discord.Embed(
                title="🎉 تم تأكيد حجزك بنجاح",
                color=discord.Color.green()
            )
            dm_embed.description = (
                f"📚 **المانهوا:** `{self.work_name}`\n"
                f"🔢 **رقم الفصل:** `{assigned_chap}`\n"
                f"🎭 **التخصص:** `{selected_role}`\n"
                f"⏱️ **المهلة:** 24 ساعة (أو حسب إعداد العمل)\n\n"
                f"📥 **روابط مجلدات الدرايف:**{links_text}\n\n"
                f"بعد الانتهاء اكتب `/تم_اكتمال_عمل` لرفع رابط عملك."
            )
            await self.target_member.send(embed=dm_embed)
            dm_status = f"📥 **تم إرسال الروابط لـ {self.target_member.mention} بالخاص!**"
        except discord.Forbidden:
            dm_status = f"⚠️ **فشل إرسال الروابط للخاص، إعدادات حساب العضو مغلقة.**"
            # تنبيه الأدمن فوراً عند فشل الـ DM
            fail_embed = discord.Embed(title="🚨 تنبيه: فشل إرسال DM للعضو", color=discord.Color.red())
            fail_embed.description = (
                f"• **العضو:** {self.target_member.mention}\n"
                f"• **السبب:** العضو أغلق الخاص — لم تصله روابط الدرايف\n"
                f"• **العمل:** `{self.work_name}` (فصل {assigned_chap}) تخصص `{selected_role}`\n"
                f"• **الإجراء المطلوب:** أرسل له الروابط يدوياً أو اطلب منه فتح الخاص"
            )
            await bot.send_admin_log(fail_embed)

        await bot.notify_admin_member_action(
            self.target_member,
            "حجز فصل جديد",
            f"• **العضو:** {self.target_member.mention}\n"
            f"• **بواسطة:** {self.author.mention}\n"
            f"• **العمل:** `{self.work_name}` (فصل {assigned_chap}) تخصص `{selected_role}`",
            discord.Color.blue()
        )

        if self.original_msg_id:
            try:
                chan = bot.get_channel(bot.COMMANDS_CHANNEL_ID)
                if chan:
                    m = await chan.fetch_message(self.original_msg_id)
                    await m.delete()
            except Exception:
                pass

        await interaction.followup.send(
            content=f"🎉 **تم تأكيد الحجز للفصل {assigned_chap}!**\n{dm_status}",
            view=None
        )


# ==========================================
# 📥 نظام تسليم الفصول المطور
# ==========================================

class CompleteSelectMenu(discord.ui.Select):
    def __init__(self, author, res_list, original_msg_id):
        self.author = author
        self.original_msg_id = original_msg_id
        options = [
            discord.SelectOption(
                label=f"{r[0]} (فصل {r[1]}) - {r[2]}",
                value=f"{r[0]}|{r[1]}|{r[2]}"
            )
            for r in res_list[:25]
        ]
        super().__init__(placeholder="📥 اختر الفصل الذي أنجزته...", options=options)

    async def callback(self, interaction: discord.Interaction):
        work, chap, role = self.values[0].split("|")
        embed = discord.Embed(
            title="❓ تأكيد إكمال المهمة",
            description=f"هل أنهيت العمل على مانهوا: **{work}** | فصل **{chap}** كتخصص (**{role}**)؟",
            color=discord.Color.orange()
        )
        await interaction.response.edit_message(
            embed=embed,
            view=CompleteExecutionView(self.author, work, int(chap), role, self.original_msg_id)
        )


class CompleteExecutionView(discord.ui.View):
    def __init__(self, author, work, chap, role, original_msg_id):
        super().__init__(timeout=60)
        self.author = author
        self.work = work
        self.chap = chap
        self.role = role
        self.original_msg_id = original_msg_id

    @discord.ui.button(label="🟢 نعم، أنجزت العمل", style=discord.ButtonStyle.success)
    async def task_done(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT time_booked FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                (self.author.id, self.work, self.chap, self.role)
            ) as cursor:
                has_res = await cursor.fetchone()

            if not has_res:
                await interaction.followup.send(
                    content="❌ لم يتم العثور على هذا الحجز بحسابك.",
                    ephemeral=True
                )
                return

            async with db.execute(
                "SELECT value FROM settings WHERE key='submission_deadline_hours'"
            ) as s_cur:
                s_row = await s_cur.fetchone()
            deadline_hours = int(s_row[0]) if s_row else 6
            deadline_time = datetime.now() + timedelta(hours=deadline_hours)

            await db.execute(
                "UPDATE reservations SET status='awaiting_submission', submission_deadline=? WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                (deadline_time.isoformat(), self.author.id, self.work, self.chap, self.role)
            )
            await db.commit()

        if self.original_msg_id:
            try:
                chan = bot.get_channel(bot.COMMANDS_CHANNEL_ID)
                if chan:
                    m = await chan.fetch_message(self.original_msg_id)
                    await m.delete()
            except Exception:
                pass

        await bot.notify_admin_member_action(
            self.author,
            "إعلان إكمال فصل",
            f"• **العضو:** {self.author.mention}\n"
            f"• **العمل:** `{self.work}` (فصل {self.chap}) تخصص `{self.role}`\n"
            f"• **الحالة:** في انتظار رفع الروابط خلال {deadline_hours} ساعة",
            discord.Color.orange()
        )

        try:
            dm_embed = discord.Embed(
                title="📤 رفع رابط الفصل المنجز",
                color=discord.Color.blue()
            )
            dm_embed.description = (
                f"أحسنت! أنت على وشك تسليم:\n"
                f"📚 **المانهوا:** `{self.work}`\n"
                f"🔢 **الفصل:** `{self.chap}`\n"
                f"🎭 **التخصص:** `{self.role}`\n\n"
                f"⏰ **لديك {deadline_hours} ساعة لرفع الروابط.**\n\n"
                f"اضغط الزر أدناه لرفع روابط الدرايف:"
            )
            view = SubmissionLinksView(self.author, self.work, self.chap, self.role)
            await self.author.send(embed=dm_embed, view=view)

            await interaction.followup.send(
                content="✅ **تم تسجيل إكمالك! تحقق من خاصك لرفع رابط الفصل.**",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                content="⚠️ **فشل إرسال طلب الروابط لخاصك. افتح الخاص وأعد المحاولة.**",
                ephemeral=True
            )
            # تنبيه الأدمن فوراً عند فشل الـ DM
            fail_embed2 = discord.Embed(title="🚨 تنبيه: فشل إرسال DM (إكمال فصل)", color=discord.Color.orange())
            fail_embed2.description = (
                f"• **العضو:** {self.author.mention}\n"
                f"• **السبب:** العضو أغلق الخاص — لم يصله طلب رفع الروابط\n"
                f"• **العمل:** `{self.work}` (فصل {self.chap}) تخصص `{self.role}`\n"
                f"• **الإجراء المطلوب:** اطلب من العضو فتح الخاص أو استخدم `/سحب_حجز_يدوي` إذا لزم"
            )
            await bot.send_admin_log(fail_embed2)

    @discord.ui.button(label="🔴 إلغاء وانسحاب (عقوبة)", style=discord.ButtonStyle.danger)
    async def task_cancelled(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT price FROM roles_config WHERE role_name=?", (self.role,)
            ) as rc_cur:
                rc_row = await rc_cur.fetchone()
            role_price = rc_row[0] if rc_row else 0.25
            penalty_fee = round(role_price * 0.1, 2)

            await db.execute(
                "DELETE FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                (self.author.id, self.work, self.chap, self.role)
            )
            await db.execute(
                "UPDATE drive_links SET is_booked=0 WHERE work_name=? AND chapter_num=? AND role=?",
                (self.work, self.chap, self.role)
            )
            profile = await get_or_create_profile(db, self.author.id, self.author.display_name)
            new_warns = profile["warnings"] + 1
            await db.execute(
                "UPDATE members_profile SET warnings=?, balance=? WHERE user_id=?",
                (new_warns, profile["balance"] - penalty_fee, self.author.id)
            )
            await db.commit()

        await bot.notify_admin_member_action(
            self.author,
            "انسحاب من مهمة",
            f"• **العضو:** {self.author.mention}\n"
            f"• **العمل:** `{self.work}` (فصل {self.chap}) تخصص `{self.role}`\n"
            f"• **العقوبة:** إنذار (`{new_warns}/3`) + خصم `{penalty_fee}$`",
            discord.Color.dark_red()
        )

        if self.original_msg_id:
            try:
                chan = bot.get_channel(bot.COMMANDS_CHANNEL_ID)
                if chan:
                    m = await chan.fetch_message(self.original_msg_id)
                    await m.delete()
            except Exception:
                pass

        await interaction.edit_original_response(
            content=f"⚠️ **تم الانسحاب وتسجيل المخالفة والخصم `{penalty_fee}$`.**",
            embed=None,
            view=None
        )


# ==========================================
# نافذة رفع الروابط (Modal) — بدل wait_for
# ==========================================

class SubmissionLinksView(discord.ui.View):
    """زر في الخاص يفتح Modal لرفع الروابط"""
    def __init__(self, member, work, chap, role):
        super().__init__(timeout=None)
        self.member = member
        self.work = work
        self.chap = chap
        self.role = role

    @discord.ui.button(label="📤 رفع روابط الدرايف", style=discord.ButtonStyle.primary)
    async def open_submission_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = SubmissionLinksModal(self.member, self.work, self.chap, self.role)
        await interaction.response.send_modal(modal)


class SubmissionLinksModal(discord.ui.Modal, title="رفع روابط الفصل المنجز"):
    رابط_الدرايف_الإجباري = discord.ui.TextInput(
        label="رابط الدرايف الإجباري",
        placeholder="https://drive.google.com/...",
        style=discord.TextStyle.short,
        required=True,
        max_length=500
    )
    رابط_الدرايف_الاختياري = discord.ui.TextInput(
        label="رابط الدرايف الاختياري (اتركه فارغاً إن لم يوجد)",
        placeholder="https://drive.google.com/... أو اتركه فارغاً",
        style=discord.TextStyle.short,
        required=False,
        max_length=500
    )

    def __init__(self, member, work, chap, role):
        super().__init__()
        self.member = member
        self.work = work
        self.chap = chap
        self.role = role

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        link1 = self.رابط_الدرايف_الإجباري.value.strip()
        link2_raw = self.رابط_الدرايف_الاختياري.value.strip()
        link2 = link2_raw if link2_raw else None

        await process_submission(self.member, self.work, self.chap, self.role, link1, link2)

        confirm_embed = discord.Embed(
            title="✅ تم استلام روابطك",
            color=discord.Color.green()
        )
        confirm_embed.description = (
            f"تم إرسال عملك للمراجعة:\n"
            f"📚 `{self.work}` فصل `{self.chap}` تخصص `{self.role}`\n"
            f"سيتم إخطارك بالنتيجة قريباً."
        )
        await interaction.followup.send(embed=confirm_embed)


async def process_submission(member: discord.Member, work: str, chap: int, role: str, link1: str, link2: str):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key='max_edit_attempts'"
        ) as s_cur:
            s_row = await s_cur.fetchone()
        max_attempts = int(s_row[0]) if s_row else 2

        async with db.execute(
            "SELECT attempts FROM chapter_submissions WHERE user_id=? AND work_name=? AND chapter_num=? AND role=? ORDER BY id DESC LIMIT 1",
            (member.id, work, chap, role)
        ) as cursor:
            prev = await cursor.fetchone()
        attempts = (prev[0] + 1) if prev else 1

        await db.execute("""
            INSERT INTO chapter_submissions
            (user_id, user_name, work_name, chapter_num, role, link1, link2, status, attempts, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?)
        """, (member.id, member.display_name, work, chap, role, link1, link2, attempts, datetime.now().isoformat()))

        await db.execute(
            "UPDATE reservations SET submission_link1=?, submission_link2=? WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
            (link1, link2, member.id, work, chap, role)
        )
        await db.commit()

    admin_channel = await bot.get_admin_log_channel()

    if admin_channel:
        review_embed = discord.Embed(
            title="📋 فصل جديد للمراجعة",
            color=discord.Color.orange()
        )
        review_embed.description = (
            f"• **العضو:** {member.mention}\n"
            f"• **المانهوا:** `{work}` (فصل {chap}) تخصص `{role}`\n"
            f"• **المحاولة رقم:** {attempts}/{max_attempts}\n"
            f"• **الرابط الإجباري:** {link1}\n"
            f"• **الرابط الاختياري:** {link2 or 'لا يوجد'}"
        )
        view = AdminReviewView(member, work, chap, role, link1, link2, attempts, max_attempts)
        review_msg = await admin_channel.send(embed=review_embed, view=view)

        async with aiosqlite.connect(bot.DB_PATH) as db:
            await db.execute(
                "UPDATE chapter_submissions SET review_msg_id=? WHERE user_id=? AND work_name=? AND chapter_num=? AND role=? AND status='pending_review'",
                (review_msg.id, member.id, work, chap, role)
            )
            await db.commit()


# ==========================================
# واجهة مراجعة الأدمن للتسليمات
# ==========================================

class AdminReviewView(discord.ui.View):
    def __init__(self, member, work, chap, role, link1, link2, attempts, max_attempts):
        super().__init__(timeout=None)
        self.member = member
        self.work = work
        self.chap = chap
        self.role = role
        self.link1 = link1
        self.link2 = link2
        self.attempts = attempts
        self.max_attempts = max_attempts

    @discord.ui.button(label="✅ قبول الفصل", style=discord.ButtonStyle.success, custom_id="admin_review_approve")
    async def approve_submission(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ هذا الزر للإدارة فقط!", ephemeral=True)
            return

        await interaction.response.defer()

        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT price FROM roles_config WHERE role_name=?", (self.role,)
            ) as r_cur:
                r_row = await r_cur.fetchone()
            base_price = r_row[0] if r_row else 0.25

            profile = await get_or_create_profile(db, self.member.id, self.member.display_name)

            async with db.execute(
                "SELECT time_booked FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                (self.member.id, self.work, self.chap, self.role)
            ) as cursor:
                bt_row = await cursor.fetchone()

            bonus_text = ""
            new_slots = profile["slots"]
            if bt_row:
                elapsed = (datetime.now() - datetime.fromisoformat(bt_row[0])).total_seconds() / 3600
                if elapsed <= 5:
                    new_slots += 1
                    bonus_text = f"\n⚡ مكافأة السرعة: رفع سعة حجزك إلى `{new_slots}`"

            effective_price = base_price
            if profile["is_excluded"] == 1:
                effective_price = 0.0
                bonus_text += "\n⚠️ العضو مستبعد - لن يُضاف رصيد"

            await db.execute(
                "DELETE FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                (self.member.id, self.work, self.chap, self.role)
            )
            await db.execute(
                "UPDATE drive_links SET is_frozen=1, is_booked=1 WHERE work_name=? AND chapter_num=? AND role=?",
                (self.work, self.chap, self.role)
            )
            await db.execute(
                "UPDATE members_profile SET balance=?, completed_chapters=?, max_slots=? WHERE user_id=?",
                (profile["balance"] + effective_price, profile["completed"] + 1, new_slots, self.member.id)
            )
            await db.execute("""
                UPDATE chapter_submissions SET status='approved', reviewed_at=?
                WHERE user_id=? AND work_name=? AND chapter_num=? AND role=? AND status='pending_review'
            """, (datetime.now().isoformat(), self.member.id, self.work, self.chap, self.role))

            await db.commit()

        # استدعاء منفصل بعد إغلاق الـ connection
        await bot.check_chapter_completion(self.work, self.chap)

        try:
            accept_embed = discord.Embed(
                title="🎉 تم قبول فصلك!",
                color=discord.Color.green()
            )
            accept_embed.description = (
                f"✅ تم قبول عملك على:\n"
                f"📚 **المانهوا:** `{self.work}` فصل `{self.chap}` تخصص `{self.role}`\n"
                f"💰 **المكافأة المضافة:** `+{effective_price:.2f}$`{bonus_text}\n\n"
                f"شكراً على جهدك يا بطل! 🍪"
            )
            await self.member.send(embed=accept_embed)
        except Exception:
            pass

        approved_embed = discord.Embed(
            title="✅ فصل مقبول",
            color=discord.Color.green()
        )
        approved_embed.description = (
            f"• **العضو:** {self.member.mention}\n"
            f"• **العمل:** `{self.work}` فصل `{self.chap}` تخصص `{self.role}`\n"
            f"• **القرار:** مقبول بواسطة {interaction.user.mention}\n"
            f"• **المكافأة:** `+{effective_price:.2f}$`"
        )
        await interaction.edit_original_response(embed=approved_embed, view=None)

        await bot.log_admin_action(
            interaction.user.display_name, "قبول_فصل",
            f"قبول {self.work} ف{self.chap} تخصص {self.role} للعضو {self.member.display_name}"
        )

    @discord.ui.button(label="❌ رفض الفصل", style=discord.ButtonStyle.danger, custom_id="admin_review_reject")
    async def reject_submission(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ هذا الزر للإدارة فقط!", ephemeral=True)
            return

        modal = RejectReasonModal(
            self.member, self.work, self.chap, self.role,
            self.attempts, self.max_attempts, interaction.message
        )
        await interaction.response.send_modal(modal)


class RejectReasonModal(discord.ui.Modal, title="سبب رفض الفصل"):
    سبب_الرفض = discord.ui.TextInput(
        label="سبب الرفض",
        placeholder="اكتب سبب الرفض هنا بالتفصيل...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    def __init__(self, member, work, chap, role, attempts, max_attempts, original_message):
        super().__init__()
        self.member = member
        self.work = work
        self.chap = chap
        self.role = role
        self.attempts = attempts
        self.max_attempts = max_attempts
        self.original_message = original_message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        reject_reason = self.سبب_الرفض.value
        is_final = self.attempts >= self.max_attempts

        async with aiosqlite.connect(bot.DB_PATH) as db:
            await db.execute("""
                UPDATE chapter_submissions SET status=?, reject_reason=?, reviewed_at=?
                WHERE user_id=? AND work_name=? AND chapter_num=? AND role=? AND status='pending_review'
            """, (
                'rejected_final' if is_final else 'rejected_edit',
                reject_reason,
                datetime.now().isoformat(),
                self.member.id, self.work, self.chap, self.role
            ))
            await db.commit()

        if is_final:
            await self._handle_final_rejection(interaction, reject_reason)
        else:
            view = RejectOptionsView(
                self.member, self.work, self.chap, self.role,
                reject_reason, self.attempts, self.max_attempts
            )
            options_embed = discord.Embed(
                title="⚠️ اختر نوع الرفض",
                color=discord.Color.orange()
            )
            options_embed.description = (
                f"**العضو:** {self.member.mention}\n"
                f"**السبب:** {reject_reason}\n"
                f"**المحاولة:** {self.attempts}/{self.max_attempts}\n\n"
                f"اختر: رفض نهائي أم طلب تعديل من العضو؟"
            )
            await interaction.followup.send(embed=options_embed, view=view, ephemeral=True)

            rejected_embed = discord.Embed(
                title="⏳ بانتظار قرار الرفض النهائي",
                color=discord.Color.yellow()
            )
            rejected_embed.description = (
                f"• **العضو:** {self.member.mention}\n"
                f"• **العمل:** `{self.work}` فصل `{self.chap}` تخصص `{self.role}`\n"
                f"• **السبب المسجل:** {reject_reason}\n"
                f"• **بانتظار:** قرار {interaction.user.mention}"
            )
            try:
                await self.original_message.edit(embed=rejected_embed, view=None)
            except Exception:
                pass

    async def _handle_final_rejection(self, interaction, reason):
        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT price FROM roles_config WHERE role_name=?", (self.role,)
            ) as rc_cur:
                rc_row = await rc_cur.fetchone()
            role_price = rc_row[0] if rc_row else 0.25
            penalty_fee = round(role_price * 0.1, 2)

            profile = await get_or_create_profile(db, self.member.id, self.member.display_name)
            await db.execute(
                "DELETE FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                (self.member.id, self.work, self.chap, self.role)
            )
            await db.execute(
                "UPDATE drive_links SET is_booked=0 WHERE work_name=? AND chapter_num=? AND role=?",
                (self.work, self.chap, self.role)
            )
            new_warns = profile["warnings"] + 1
            await db.execute(
                "UPDATE members_profile SET warnings=?, balance=? WHERE user_id=?",
                (new_warns, profile["balance"] - penalty_fee, self.member.id)
            )
            await db.commit()

        try:
            reject_embed = discord.Embed(
                title="❌ رفض نهائي للفصل",
                color=discord.Color.red()
            )
            reject_embed.description = (
                f"تم رفض عملك على:\n"
                f"📚 **المانهوا:** `{self.work}` فصل `{self.chap}` تخصص `{self.role}`\n\n"
                f"📝 **سبب الرفض:** {reason}\n\n"
                f"⚠️ هذا رفض نهائي، تم تسجيل إنذار وخصم `{penalty_fee}$`."
            )
            await self.member.send(embed=reject_embed)
        except Exception:
            pass

        final_embed = discord.Embed(
            title="❌ رفض نهائي",
            color=discord.Color.red()
        )
        final_embed.description = (
            f"• **العضو:** {self.member.mention}\n"
            f"• **العمل:** `{self.work}` فصل `{self.chap}` تخصص `{self.role}`\n"
            f"• **السبب:** {reason}\n"
            f"• **القرار:** رفض نهائي بواسطة {interaction.user.mention}"
        )
        try:
            await self.original_message.edit(embed=final_embed, view=None)
        except Exception:
            pass

        await bot.log_admin_action(
            interaction.user.display_name, "رفض_نهائي",
            f"رفض نهائي {self.work} ف{self.chap} تخصص {self.role} للعضو {self.member.display_name}: {reason}"
        )


class RejectOptionsView(discord.ui.View):
    def __init__(self, member, work, chap, role, reason, attempts, max_attempts):
        super().__init__(timeout=120)
        self.member = member
        self.work = work
        self.chap = chap
        self.role = role
        self.reason = reason
        self.attempts = attempts
        self.max_attempts = max_attempts

    @discord.ui.button(label="🔄 طلب تعديل من العضو", style=discord.ButtonStyle.primary)
    async def request_edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        try:
            edit_embed = discord.Embed(
                title="🔄 مطلوب تعديل على الفصل",
                color=discord.Color.yellow()
            )
            edit_embed.description = (
                f"تم رفض فصلك مؤقتاً ومطلوب منك تعديل:\n"
                f"📚 **المانهوا:** `{self.work}` فصل `{self.chap}` تخصص `{self.role}`\n\n"
                f"📝 **سبب الرفض:** {self.reason}\n\n"
                f"⚠️ **المحاولة {self.attempts}/{self.max_attempts}**\n"
                f"يرجى إعادة رفع الروابط المعدلة عبر الزر أدناه:"
            )
            view = SubmissionLinksView(self.member, self.work, self.chap, self.role)
            await self.member.send(embed=edit_embed, view=view)
        except discord.Forbidden:
            pass

        await interaction.followup.send(
            content=f"✅ تم إخطار {self.member.mention} بطلب التعديل.",
            ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="❌ رفض نهائي", style=discord.ButtonStyle.danger)
    async def final_reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT price FROM roles_config WHERE role_name=?", (self.role,)
            ) as rc_cur:
                rc_row = await rc_cur.fetchone()
            role_price = rc_row[0] if rc_row else 0.25
            penalty_fee = round(role_price * 0.1, 2)

            profile = await get_or_create_profile(db, self.member.id, self.member.display_name)
            await db.execute(
                "DELETE FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
                (self.member.id, self.work, self.chap, self.role)
            )
            await db.execute(
                "UPDATE drive_links SET is_booked=0 WHERE work_name=? AND chapter_num=? AND role=?",
                (self.work, self.chap, self.role)
            )
            new_warns = profile["warnings"] + 1
            await db.execute(
                "UPDATE members_profile SET warnings=?, balance=? WHERE user_id=?",
                (new_warns, profile["balance"] - penalty_fee, self.member.id)
            )
            await db.execute("""
                UPDATE chapter_submissions SET status='rejected_final', reviewed_at=?
                WHERE user_id=? AND work_name=? AND chapter_num=? AND role=? AND status IN ('rejected_edit', 'pending_review')
            """, (datetime.now().isoformat(), self.member.id, self.work, self.chap, self.role))
            await db.commit()

        try:
            final_embed = discord.Embed(
                title="❌ رفض نهائي للفصل",
                color=discord.Color.red()
            )
            final_embed.description = (
                f"تم الرفض النهائي لعملك على:\n"
                f"📚 **المانهوا:** `{self.work}` فصل `{self.chap}` تخصص `{self.role}`\n\n"
                f"📝 **سبب الرفض:** {self.reason}\n\n"
                f"⚠️ تم تسجيل إنذار وخصم `{penalty_fee}$` من محفظتك."
            )
            await self.member.send(embed=final_embed)
        except Exception:
            pass

        await bot.log_admin_action(
            interaction.user.display_name, "رفض_نهائي_يدوي",
            f"رفض نهائي {self.work} ف{self.chap} تخصص {self.role} للعضو {self.member.display_name}"
        )

        await interaction.followup.send(
            content=f"✅ تم تطبيق الرفض النهائي على {self.member.mention}.",
            ephemeral=True
        )
        self.stop()


# ==========================================
# 🍪 أوامر الـ Slash Commands العامة
# ==========================================

@bot.tree.command(name="حجز_عمل", description="البدء في حجز فصل جديد بمانهوا واستلام روابط المجلدات بالخاص")
async def slash_direct_booking(interaction: discord.Interaction):
    profile = await get_profile_standalone(interaction.user.id, interaction.user.display_name)
    if profile["is_excluded"] == 1:
        await interaction.response.send_message(
            "🚫 **أنت مستبعد حالياً ولا يمكنك الحجز. تواصل مع الإدارة.**",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        content="🍪 **نظام الحجوزات الحية | تيم كوكيز:** اضغط بالأسفل للبدء:",
        ephemeral=False
    )
    msg = await interaction.original_response()
    await msg.edit(view=DirectBookLauncher(interaction.user, None, msg.id))


@bot.tree.command(name="تم_اكتمال_عمل", description="إعلان إنهاء الفصل ورفع رابط العمل للمراجعة")
async def completed_work(interaction: discord.Interaction):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT work_name, chapter_num, role FROM reservations WHERE user_id=? AND status='pending'",
            (interaction.user.id,)
        ) as cursor:
            res_list = await cursor.fetchall()

    if not res_list:
        await interaction.response.send_message(
            "📭 لا يوجد لديك حجوزات نشطة لتسليمها.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "📥 اختر المهمة المكتملة من القائمة:",
        ephemeral=False
    )
    msg = await interaction.original_response()
    view = discord.ui.View()
    view.add_item(CompleteSelectMenu(interaction.user, res_list, msg.id))
    await msg.edit(view=view)


@bot.tree.command(name="رصيدي", description="عرض ملفك الشخصي وأرباحك وإنذاراتك")
async def my_profile(interaction: discord.Interaction):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, interaction.user.id, interaction.user.display_name)
    embed = discord.Embed(
        title=f"👤 الملف الشخصي: {interaction.user.display_name}",
        color=discord.Color.teal()
    )
    status_str = "🚫 مستبعد" if p["is_excluded"] == 1 else "✅ نشط"
    embed.add_field(name="💰 الأرباح الصافية", value=f"**{p['balance']:.2f}$**", inline=True)
    embed.add_field(name="⚠️ الإنذارات", value=f"**{p['warnings']}/3**", inline=True)
    embed.add_field(name="📚 الفصول المنجزة", value=f"**{p['completed']} فصل**", inline=True)
    embed.add_field(name="⚡ سعة الحجز", value=f"**{p['slots']} فصول**", inline=True)
    embed.add_field(name="🔖 الحالة", value=status_str, inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="كشف_اعمال_شخص", description="عرض ملف وحجوزات عضو معين")
@app_commands.rename(member="العضو")
@app_commands.describe(member="اختر العضو المراد عرض ملفه")
async def inspect_member(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)
        async with db.execute("""
            SELECT r.work_name, r.chapter_num, r.role, r.time_booked, COALESCE(w.max_hours, 24), r.status
            FROM reservations r
            LEFT JOIN works w ON r.work_name = w.name
            WHERE r.user_id=?
        """, (member.id,)) as cursor:
            res_list = await cursor.fetchall()

    embed = discord.Embed(
        title=f"🔍 ملف العضو: {member.display_name}",
        color=discord.Color.blue()
    )
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)

    status_str = "🚫 مستبعد" if p["is_excluded"] == 1 else "✅ نشط"
    embed.add_field(name="💰 الرصيد", value=f"`{p['balance']:.2f}$`", inline=True)
    embed.add_field(name="⚠️ الإنذارات", value=f"`{p['warnings']}/3`", inline=True)
    embed.add_field(name="📚 الفصول المنجزة", value=f"`{p['completed']} فصل`", inline=True)
    embed.add_field(name="🔖 الحالة", value=status_str, inline=True)

    res_text = ""
    if res_list:
        for idx, (work, chap, role, b_time, max_hours, status) in enumerate(res_list, 1):
            dt = datetime.fromisoformat(b_time)
            elapsed = datetime.now() - dt
            remaining_hours = max(0, max_hours - int(elapsed.total_seconds() / 3600))
            status_str2 = "🔄 تسليم" if status == 'awaiting_submission' else "⏳ قيد العمل"
            res_text += f"{idx}. **{work}** (فصل {chap}) ➔ `{role}` [{remaining_hours}h] {status_str2}\n"
    else:
        res_text = "❌ لا توجد حجوزات نشطة."

    embed.add_field(name="📋 الحجوزات الحالية:", value=res_text, inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="احصائيات", description="عرض إحصائيات عامة لتيم كوكيز")
async def general_stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    try:
        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM works WHERE is_active=1") as c1:
                active_w = (await c1.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM reservations") as c2:
                active_res = (await c2.fetchone())[0]
            async with db.execute("SELECT SUM(completed_chapters), SUM(balance) FROM members_profile") as c3:
                row = await c3.fetchone()
            async with db.execute("SELECT COUNT(*) FROM members_profile WHERE is_excluded=1") as c4:
                excluded_count = (await c4.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM chapter_submissions WHERE status='pending_review'") as c5:
                pending_review = (await c5.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM members_profile") as c6:
                total_members = (await c6.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM chapter_submissions WHERE status='approved'") as c7:
                total_approved = (await c7.fetchone())[0]

        total_chaps = row[0] if row[0] else 0
        total_funds = row[1] if row[1] else 0.0

        embed = discord.Embed(
            title="📊 الإحصائيات العامة | تيم كوكيز",
            color=discord.Color.magenta(),
            timestamp=datetime.now()
        )
        embed.add_field(name="📚 الأعمال النشطة", value=f"`{active_w}` مانهوا", inline=True)
        embed.add_field(name="📥 الحجوزات الجارية", value=f"`{active_res}` فصل", inline=True)
        embed.add_field(name="👥 إجمالي الأعضاء", value=f"`{total_members}` عضو", inline=True)
        embed.add_field(name="🎉 إجمالي الفصول المنجزة", value=f"`{total_chaps}` فصل", inline=True)
        embed.add_field(name="✅ فصول مقبولة (تسليم)", value=f"`{total_approved}` فصل", inline=True)
        embed.add_field(name="💸 إجمالي المستحقات", value=f"`{total_funds:.2f}$`", inline=True)
        embed.add_field(name="🔍 بانتظار المراجعة", value=f"`{pending_review}` فصل", inline=True)
        embed.add_field(name="🚫 أعضاء مستبعدون", value=f"`{excluded_count}` عضو", inline=True)
        embed.set_footer(text="تيم كوكيز | آخر تحديث")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        logger.error(f"خطأ في أمر احصائيات: {e}")
        await interaction.followup.send(content="❌ حدث خطأ أثناء جلب الإحصائيات.", ephemeral=True)


@bot.tree.command(name="أسعار", description="استعراض قائمة الأسعار الحالية لكافة التخصصات")
async def view_prices(interaction: discord.Interaction):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT role_name, price, is_enabled FROM roles_config") as cursor:
            rows = await cursor.fetchall()

    embed = discord.Embed(
        title="💰 لائحة الأسعار ومكافآت الإنتاج",
        color=discord.Color.gold()
    )
    desc = ""
    for r_name, r_price, r_status in rows:
        status_str = "🟢 مفعّل" if r_status == 1 else "🔴 معطّل"
        desc += f"• **{r_name}:** `{r_price:.2f}$` لكل فصل | {status_str}\n"
    embed.description = desc
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="قائمة_اعمال", description="عرض كل الأعمال النشطة مع حالتها وتوفر التخصصات")
async def list_active_works(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT name, current_chapter, max_hours, required_roles FROM works WHERE is_active=1 ORDER BY name ASC"
        ) as cursor:
            works = await cursor.fetchall()

        if not works:
            await interaction.followup.send(content="📭 لا توجد أعمال نشطة حالياً.")
            return

        embed = discord.Embed(
            title="📚 قائمة الأعمال النشطة | تيم كوكيز",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        for w_name, w_chap, w_hours, w_req in works:
            async with db.execute(
                "SELECT role FROM drive_links WHERE work_name=? AND chapter_num=? AND is_booked=0 AND is_frozen=0",
                (w_name, w_chap)
            ) as cursor:
                available_roles = [r[0] for r in await cursor.fetchall()]

            async with db.execute(
                "SELECT COUNT(*) FROM reservations WHERE work_name=? AND chapter_num=?",
                (w_name, w_chap)
            ) as cursor:
                active_bookings = (await cursor.fetchone())[0]

            roles_text = ", ".join(f"`{r}`" for r in available_roles) if available_roles else "لا توجد تخصصات متاحة"
            embed.add_field(
                name=f"📖 {w_name}",
                value=(
                    f"الفصل الحالي: **{w_chap}** | المهلة: `{w_hours}h`\n"
                    f"حجوزات نشطة: `{active_bookings}` | التخصصات المتاحة: {roles_text}"
                ),
                inline=False
            )

    embed.set_footer(text="استخدم /حجز_عمل للحجز الآن")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="كشف_فصل", description="عرض حالة فصل معين وكل التخصصات العاملة عليه")
@app_commands.rename(work_name="اسم_العمل", chapter_num="رقم_الفصل")
@app_commands.describe(work_name="اختر اسم المانهوا", chapter_num="أدخل رقم الفصل")
@app_commands.autocomplete(work_name=autocomplete_all_works)
async def inspect_chapter(interaction: discord.Interaction, work_name: str, chapter_num: int):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT role, drive_url1, is_booked, is_frozen FROM drive_links WHERE work_name=? AND chapter_num=?",
            (work_name, chapter_num)
        ) as cursor:
            drive_data = await cursor.fetchall()

        async with db.execute(
            "SELECT user_id, user_name, role, time_booked, status FROM reservations WHERE work_name=? AND chapter_num=?",
            (work_name, chapter_num)
        ) as cursor:
            reservations = await cursor.fetchall()

        async with db.execute(
            "SELECT user_name, role, status, submitted_at FROM chapter_submissions WHERE work_name=? AND chapter_num=? ORDER BY submitted_at DESC",
            (work_name, chapter_num)
        ) as cursor:
            submissions = await cursor.fetchall()

    embed = discord.Embed(
        title=f"🔍 حالة الفصل | {work_name} - فصل {chapter_num}",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )

    if not drive_data and not reservations:
        embed.description = "❌ لا توجد بيانات لهذا الفصل."
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    roles_status = ""
    for role, url, is_booked, is_frozen in drive_data:
        if is_frozen:
            icon = "✅"
            state = "مكتمل ومجمد"
        elif is_booked:
            icon = "🔄"
            state = "محجوز"
        else:
            icon = "⭕"
            state = "متاح"
        roles_status += f"{icon} **{role}**: {state}\n"

    if roles_status:
        embed.add_field(name="📋 حالة التخصصات:", value=roles_status, inline=False)

    if reservations:
        res_text = ""
        for uid, uname, role, b_time, status in reservations:
            elapsed = datetime.now() - datetime.fromisoformat(b_time)
            hours_elapsed = int(elapsed.total_seconds() / 3600)
            status_icon = "🔄" if status == 'awaiting_submission' else "⏳"
            res_text += f"{status_icon} <@{uid}> (`{uname}`) - `{role}` ({hours_elapsed}h مضت)\n"
        embed.add_field(name="👥 العاملون الآن:", value=res_text, inline=False)

    if submissions:
        sub_text = ""
        for uname, role, status, sub_at in submissions[:5]:
            status_map = {
                'approved': '✅ مقبول',
                'pending_review': '⏳ قيد المراجعة',
                'rejected_final': '❌ مرفوض',
                'rejected_edit': '🔄 طلب تعديل'
            }
            status_label = status_map.get(status, status)
            sub_text += f"• `{uname}` - `{role}` [{status_label}]\n"
        embed.add_field(name="📤 التسليمات:", value=sub_text, inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


# ==========================================
# 📖 نظام مبوب لعرض الأوامر (Help)
# ==========================================

class HelpDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="👤 أوامر الأعضاء العامة",
                description="الحجز، الحساب، الأسعار",
                value="أعضاء"
            ),
            discord.SelectOption(
                label="👑 أوامر الإدارة العامة",
                description="تعديل القنوات، الحجوزات والأعمال",
                value="إدارة_عامة"
            ),
            discord.SelectOption(
                label="💸 أوامر الإدارة المالية",
                description="المكافآت، الخصومات، التقارير",
                value="إدارة_مالية"
            ),
            discord.SelectOption(
                label="⚙️ أوامر الأوامر المخصصة",
                description="إضافة وحذف الأوامر الجاهزة",
                value="أوامر_مخصصة"
            )
        ]
        super().__init__(placeholder="📂 اختر فئة الأوامر...", options=options)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        embed = discord.Embed(color=discord.Color.blue())

        if category == "أعضاء":
            embed.title = "👤 أوامر الأعضاء"
            embed.description = (
                "`/حجز_عمل` ➔ حجز فصل واستلام روابط الدرايف بالخاص.\n"
                "`/تم_اكتمال_عمل` ➔ رفع رابط العمل للمراجعة وإغلاق الحجز.\n"
                "`/رصيدي` ➔ عرض أرباحك وإنذاراتك وسعة حجزك.\n"
                "`/كشف_اعمال_شخص` ➔ استعراض ملف وحجوزات عضو آخر.\n"
                "`/احصائيات` ➔ إحصائيات الإنتاج في السيرفر.\n"
                "`/أسعار` ➔ التخصصات والأسعار المعتمدة.\n"
                "`/قائمة_اعمال` ➔ عرض كل الأعمال النشطة وحالتها.\n"
                "`/كشف_فصل` ➔ مراقبة حالة فصل معين بالتفصيل."
            )
        elif category == "إدارة_عامة":
            embed.title = "👑 أوامر الإدارة العامة"
            embed.description = (
                "`/اعدادت_بوت` ➔ عرض إعدادات القنوات وموعد الدفع.\n"
                "`/تحديد_قنوات` ➔ تخصيص قنوات العمليات والسجلات والباك أب.\n"
                "`/اضافة_عمل` ➔ إضافة مانهوا جديدة للسيستم.\n"
                "`/اضافة_رابط_عمل` ➔ إضافة روابط فصول لمانهوا.\n"
                "`/تغير_مدة_حجز` ➔ تعديل المهلة لمانهوا معينة.\n"
                "`/تعديل_عمل` ➔ تعديل الفصل الحالي لمانهوا نشطة.\n"
                "`/تعديل_تخصصات_مطلوبة` ➔ تحديد عدد التخصصات المطلوبة.\n"
                "`/حذف_عمل` ➔ حذف عمل نهائياً.\n"
                "`/حذف_جميع_أعمال` ➔ مسح شامل لكافة الأعمال.\n"
                "`/حجز_عمل_لغيري` ➔ إسناد حجز لعضو آخر يدوياً.\n"
                "`/سحب_حجز_يدوي` ➔ إلغاء حجز من عضو يدوياً.\n"
                "`/حذف_سجل_عضو` ➔ حذف ملف عضو بالكامل.\n"
                "`/تعديل_سجل_عضو` ➔ تعديل فصول عضو أو إنذاراته.\n"
                "`/استبعاد_عضو` ➔ استبعاد عضو وتجميد رصيده.\n"
                "`/الغاء_استبعاد_عضو` ➔ إلغاء استبعاد عضو.\n"
                "`/تحذير_عضو` ➔ إرسال تحذير رسمي لعضو.\n"
                "`/بدون_حجوزات` ➔ قائمة الأعضاء بدون حجوزات نشطة.\n"
                "`/سجل_عرض_آخر_عشرين_امر` ➔ آخر 20 عملية إدارية."
            )
        elif category == "إدارة_مالية":
            embed.title = "💸 أوامر الإدارة المالية"
            embed.description = (
                "`/تغير_أسعار` ➔ تعديل سعر تخصص.\n"
                "`/اضافة_تخصص` ➔ إضافة تخصص جديد.\n"
                "`/حذف_تخصص` ➔ مسح تخصص نهائياً.\n"
                "`/تفعيل_تخصص` / `/تعطيل_تخصص` ➔ التحكم في إتاحة التخصص.\n"
                "`/مكافأة` ➔ إضافة أرباح استثنائية لعضو.\n"
                "`/خصم` ➔ خصم مالي من محفظة عضو.\n"
                "`/تعديل_رصيد` ➔ تعديل الرصيد الصافي لعضو.\n"
                "`/تحديد_موعد_دفع` ➔ تدوين موعد توزيع الأرصدة.\n"
                "`/تقرير_دفع` ➔ كشف الأرصدة للتسليم.\n"
                "`/تقرير_أسبوعي` ➔ ملخص الإنتاج الأسبوعي.\n"
                "`/تصفير_الشهر` ➔ تصفير الأرصدة لدورة جديدة.\n"
                "`/تصدير_البيانات` ➔ استخراج ملف JSON احتياطي.\n"
                "`/أدمن_استيراد_بيانات` ➔ استيراد بيانات من ملف JSON.\n"
                "`/مستجدات_نهاية_الشهر` ➔ التقرير المالي الختامي."
            )
        elif category == "أوامر_مخصصة":
            embed.title = "⚙️ الأوامر المخصصة"
            embed.description = (
                "`/اضافة_امر` ➔ إضافة أمر جاهز برد مخصص.\n"
                "`/حذف_امر_مخصص` ➔ حذف أمر مخصص.\n"
                "`/قائمة_اوامر_مخصصة` ➔ عرض كل الأوامر المخصصة المضافة."
            )
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(HelpDropdown())


@bot.tree.command(name="عرض_جميع_الأوامر", description="دليل تفاعلي لكافة أوامر البوت")
async def show_all_commands(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🍪 دليل الأوامر الشامل | تيم كوكيز",
        description="اختر فئة الأوامر من القائمة المنسدلة:",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=HelpView())


# ==========================================
# 👑 الأوامر الإدارية
# ==========================================

@bot.tree.command(name="اعدادت_بوت", description="إدارة: عرض إعدادات القنوات وموعد الدفع")
@app_commands.checks.has_permissions(administrator=True)
async def view_bot_settings(interaction: discord.Interaction):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key='pay_day_notice'") as c1:
            pay_day = (await c1.fetchone())[0]
        async with db.execute("SELECT value FROM settings WHERE key='submission_deadline_hours'") as c2:
            sub_hours = (await c2.fetchone())[0]
        async with db.execute("SELECT value FROM settings WHERE key='max_edit_attempts'") as c3:
            max_edit = (await c3.fetchone())[0]

    embed = discord.Embed(title="⚙️ إعدادات البوت الحالية", color=discord.Color.dark_grey())
    embed.add_field(name="📁 روم العمليات", value=f"<#{bot.COMMANDS_CHANNEL_ID}>", inline=False)
    embed.add_field(name="🚨 روم السجل الإداري", value=f"<#{bot.ADMIN_LOG_CHANNEL_ID}>", inline=False)
    embed.add_field(name="📦 روم الباك أب", value=f"<#{bot.BACKUP_CHANNEL_ID}>", inline=False)
    embed.add_field(name="📆 موعد الدفع", value=f"**{pay_day}**", inline=False)
    embed.add_field(name="⏰ مهلة رفع الروابط", value=f"**{sub_hours} ساعة**", inline=True)
    embed.add_field(name="🔄 أقصى محاولات تعديل", value=f"**{max_edit} محاولات**", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="تحديد_قنوات", description="إدارة: تخصيص قنوات العمليات والسجلات والباك أب")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(operations_channel="قناة_العمليات", admin_log_channel="قناة_السجل_الإداري", backup_channel="قناة_الباك_أب")
@app_commands.describe(
    operations_channel="اختر قناة العمليات",
    admin_log_channel="اختر قناة السجل الإداري",
    backup_channel="اختر قناة الباك أب"
)
async def set_bot_channels(
    interaction: discord.Interaction,
    operations_channel: discord.TextChannel = None,
    admin_log_channel: discord.TextChannel = None,
    backup_channel: discord.TextChannel = None
):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        if operations_channel:
            await db.execute("UPDATE settings SET value=? WHERE key='commands_channel'", (str(operations_channel.id),))
            bot.COMMANDS_CHANNEL_ID = operations_channel.id
        if admin_log_channel:
            await db.execute("UPDATE settings SET value=? WHERE key='admin_log_channel'", (str(admin_log_channel.id),))
            bot.ADMIN_LOG_CHANNEL_ID = admin_log_channel.id
        if backup_channel:
            await db.execute("UPDATE settings SET value=? WHERE key='backup_channel'", (str(backup_channel.id),))
            bot.BACKUP_CHANNEL_ID = backup_channel.id
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "تحديد_قنوات", "تعديل القنوات.")
    await interaction.followup.send(content="✅ **تم تحديث إعدادات القنوات بنجاح!**", ephemeral=True)


@bot.tree.command(name="اضافة_عمل", description="إدارة: إضافة مانهوا جديدة للسيستم")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(work_name="اسم_العمل", starting_chapter="الفصل_الابتدائي", max_hours="المهلة_بالساعات", required_roles="التخصصات_المطلوبة")
@app_commands.describe(
    work_name="اكتب اسم المانهوا",
    starting_chapter="رقم الفصل الابتدائي (افتراضي: 1)",
    max_hours="المهلة بالساعات (افتراضي: 24)",
    required_roles="عدد التخصصات المطلوبة (افتراضي: 3)"
)
async def add_new_work(
    interaction: discord.Interaction,
    work_name: str,
    starting_chapter: int = 1,
    max_hours: int = 24,
    required_roles: int = 3
):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT name FROM works WHERE name=?", (work_name,)) as cursor:
            existing = await cursor.fetchone()

        if existing:
            await interaction.followup.send(
                content=f"❌ المانهوا **{work_name}** موجودة مسبقاً. استخدم `/تعديل_عمل` للتعديل.",
                ephemeral=True
            )
            return

        await db.execute(
            "INSERT INTO works (name, current_chapter, is_active, max_hours, required_roles) VALUES (?, ?, 1, ?, ?)",
            (work_name, starting_chapter, max_hours, required_roles)
        )
        await db.commit()

    await bot.log_admin_action(
        interaction.user.display_name, "اضافة_عمل",
        f"إضافة {work_name} من فصل {starting_chapter}"
    )

    log_embed = discord.Embed(title="📚 إضافة مانهوا جديدة", color=discord.Color.green())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **المانهوا:** `{work_name}`\n"
        f"• **الفصل الابتدائي:** {starting_chapter}\n"
        f"• **المهلة:** {max_hours} ساعة\n"
        f"• **التخصصات المطلوبة:** {required_roles}"
    )
    await bot.send_admin_log(log_embed)
    await interaction.followup.send(
        content=f"✅ تم إضافة مانهوا **{work_name}** بنجاح من الفصل **{starting_chapter}**.",
        ephemeral=True
    )


@bot.tree.command(name="اضافة_رابط_عمل", description="إدارة: إضافة روابط فصل لمانهوا ومهمة بالقوائم")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(
    work_name="اسم_العمل",
    role="التخصص",
    chapter_num="رقم_الفصل",
    max_hours="المهلة_بالساعات",
    drive_url1="رابط_الدرايف_1",
    drive_url2="رابط_الدرايف_2",
    drive_url3="رابط_الدرايف_3",
    drive_url4="رابط_الدرايف_4"
)
@app_commands.describe(
    work_name="اختر اسم المانهوا",
    role="اختر التخصص",
    chapter_num="أدخل رقم الفصل",
    max_hours="أدخل المهلة بالساعات",
    drive_url1="أدخل رابط الدرايف الأول (إجباري)",
    drive_url2="أدخل رابط الدرايف الثاني (اختياري)",
    drive_url3="أدخل رابط الدرايف الثالث (اختياري)",
    drive_url4="أدخل رابط الدرايف الرابع (اختياري)"
)
@app_commands.autocomplete(work_name=autocomplete_all_works, role=autocomplete_all_roles)
async def add_work_link(
    interaction: discord.Interaction,
    work_name: str,
    role: str,
    chapter_num: int,
    max_hours: int,
    drive_url1: str,
    drive_url2: str = None,
    drive_url3: str = None,
    drive_url4: str = None
):
    await interaction.response.defer(ephemeral=True)

    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT name FROM works WHERE name=?", (work_name,)) as cursor:
            work_exists = await cursor.fetchone()

        if not work_exists:
            await db.execute(
                "INSERT OR IGNORE INTO works (name, current_chapter, is_active, max_hours, required_roles) VALUES (?, ?, 1, ?, 3)",
                (work_name, chapter_num, max_hours)
            )

        async with db.execute("SELECT is_enabled FROM roles_config WHERE role_name=?", (role,)) as cursor:
            role_exists = await cursor.fetchone()

        if not role_exists:
            await interaction.followup.send(
                content=f"❌ التخصص `{role}` غير موجود. أضفه عبر `/اضافة_تخصص`.",
                ephemeral=True
            )
            return

        await db.execute(
            """INSERT INTO drive_links
            (work_name, chapter_num, role, drive_url1, drive_url2, drive_url3, drive_url4, is_booked, is_frozen)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)
            ON CONFLICT(work_name, chapter_num, role)
            DO UPDATE SET drive_url1=?, drive_url2=?, drive_url3=?, drive_url4=?, is_booked=0, is_frozen=0""",
            (work_name, chapter_num, role, drive_url1, drive_url2, drive_url3, drive_url4,
             drive_url1, drive_url2, drive_url3, drive_url4)
        )

        await db.execute(
            "UPDATE works SET max_hours=? WHERE name=?",
            (max_hours, work_name)
        )
        await db.commit()

    await bot.log_admin_action(
        interaction.user.display_name, "اضافة_رابط_عمل",
        f"{work_name} ف{chapter_num} تخصص {role}"
    )

    log_embed = discord.Embed(title="🔗 إضافة رابط فصل", color=discord.Color.blue())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **المانهوا:** `{work_name}` فصل `{chapter_num}`\n"
        f"• **التخصص:** `{role}`\n"
        f"• **المهلة:** `{max_hours}` ساعة\n"
        f"• **رابط 1:** {drive_url1}\n"
        f"• **رابط 2:** {drive_url2 or 'لا يوجد'}\n"
        f"• **رابط 3:** {drive_url3 or 'لا يوجد'}\n"
        f"• **رابط 4:** {drive_url4 or 'لا يوجد'}"
    )
    await bot.send_admin_log(log_embed)

    commands_channel = bot.get_channel(bot.COMMANDS_CHANNEL_ID)
    if commands_channel:
        ann_embed = discord.Embed(
            title="📢 فصل جديد متاح للحجز! | تيم كوكيز",
            color=discord.Color.green()
        )
        ann_embed.description = (
            f"🚀 تم إضافة فصل جديد لمانهوا: **{work_name}**\n\n"
            f"• **التخصص المطلوب:** `{role}`\n"
            f"• **رقم الفصل:** `{chapter_num}`\n"
            f"• **مهلة العمل:** `{max_hours}` ساعة\n\n"
            f"👇 اكتب `/حجز_عمل` الآن للبدء!"
        )
        try:
            await commands_channel.send(content="@everyone", embed=ann_embed)
        except Exception:
            pass

    await interaction.followup.send(
        content=f"✅ **تم إضافة الفصل {chapter_num} لمانهوا {work_name} تخصص {role} بنجاح!**",
        ephemeral=True
    )


@bot.tree.command(name="تغير_مدة_حجز", description="إدارة: تعديل المهلة الافتراضية لمانهوا معينة بالساعات")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(work_name="اسم_العمل", hours="المهلة_بالساعات")
@app_commands.describe(work_name="اختر اسم المانهوا", hours="أدخل المهلة الجديدة بالساعات")
@app_commands.autocomplete(work_name=autocomplete_all_works)
async def change_work_deadline(interaction: discord.Interaction, work_name: str, hours: int):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT name FROM works WHERE name=?", (work_name,)) as cursor:
            if not await cursor.fetchone():
                await interaction.followup.send(content="❌ العمل غير موجود.", ephemeral=True)
                return
        await db.execute("UPDATE works SET max_hours=? WHERE name=?", (hours, work_name))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "تغير_مدة_حجز", f"{work_name} → {hours} ساعة")
    await interaction.followup.send(
        content=f"✅ تم تعديل مهلة **{work_name}** إلى **{hours} ساعة**.", ephemeral=True
    )


@bot.tree.command(name="تعديل_تخصصات_مطلوبة", description="إدارة: تحديد عدد التخصصات المطلوبة لتقدم فصل عمل معين")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(work_name="اسم_العمل", required_count="عدد_التخصصات")
@app_commands.describe(work_name="اختر اسم المانهوا", required_count="أدخل عدد التخصصات المطلوبة")
@app_commands.autocomplete(work_name=autocomplete_all_works)
async def set_required_roles(interaction: discord.Interaction, work_name: str, required_count: int):
    await interaction.response.defer(ephemeral=True)
    if required_count < 1:
        await interaction.followup.send(content="❌ العدد يجب أن يكون 1 على الأقل.", ephemeral=True)
        return

    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT name FROM works WHERE name=?", (work_name,)) as cursor:
            if not await cursor.fetchone():
                await db.execute(
                    "INSERT INTO works (name, current_chapter, is_active, required_roles) VALUES (?, 1, 1, ?)",
                    (work_name, required_count)
                )
            else:
                await db.execute(
                    "UPDATE works SET required_roles=? WHERE name=?",
                    (required_count, work_name)
                )
        await db.commit()

    await bot.log_admin_action(
        interaction.user.display_name, "تعديل_تخصصات_مطلوبة",
        f"{work_name} → {required_count} تخصصات مطلوبة"
    )
    await interaction.followup.send(
        content=f"✅ تم تعديل عدد التخصصات المطلوبة لـ **{work_name}** إلى **{required_count} تخصصات**.",
        ephemeral=True
    )


@bot.tree.command(name="تعديل_عمل", description="إدارة: تعديل الفصل الحالي لمانهوا نشطة")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(work_name="اسم_العمل", current_chapter="رقم_الفصل_الحالي")
@app_commands.describe(work_name="اختر اسم المانهوا", current_chapter="أدخل رقم الفصل الجديد")
@app_commands.autocomplete(work_name=autocomplete_all_works)
async def modify_work_chapter(interaction: discord.Interaction, work_name: str, current_chapter: int):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("UPDATE works SET current_chapter=? WHERE name=?", (current_chapter, work_name))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "تعديل_عمل", f"{work_name} → فصل {current_chapter}")
    await interaction.followup.send(
        content=f"✅ تم تعديل فصل **{work_name}** إلى الفصل **{current_chapter}**.", ephemeral=True
    )


@bot.tree.command(name="حذف_عمل", description="إدارة: حذف مانهوا نهائياً من السيستم")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(work_name="اسم_العمل")
@app_commands.describe(work_name="اختر المانهوا المراد حذفها")
@app_commands.autocomplete(work_name=autocomplete_all_works)
async def delete_single_work(interaction: discord.Interaction, work_name: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("DELETE FROM works WHERE name=?", (work_name,))
        await db.execute("DELETE FROM drive_links WHERE work_name=?", (work_name,))
        await db.execute("DELETE FROM reservations WHERE work_name=?", (work_name,))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "حذف_عمل", f"مسح {work_name}")
    await interaction.followup.send(content=f"✅ تم مسح **{work_name}** بالكامل.", ephemeral=True)


@bot.tree.command(name="حذف_جميع_أعمال", description="إدارة: مسح شامل لكافة الأعمال")
@app_commands.checks.has_permissions(administrator=True)
async def delete_all_works_completely(interaction: discord.Interaction):
    embed = discord.Embed(title="⚠️⚠️ خطر: حذف جميع الأعمال", color=discord.Color.dark_red())
    embed.description = (
        "**هذا الإجراء سيحذف بشكل نهائي:**\n"
        "• جميع الأعمال (المانهوا)\n"
        "• جميع روابط الدرايف\n"
        "• جميع الحجوزات النشطة\n\n"
        "⛔ **لا رجعة في هذا الإجراء!**"
    )
    view = ConfirmDeleteAllView(interaction.user)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ConfirmDeleteAllView(discord.ui.View):
    def __init__(self, admin_user):
        super().__init__(timeout=30)
        self.admin_user = admin_user

    @discord.ui.button(label="✅ نعم، احذف الكل نهائياً", style=discord.ButtonStyle.danger)
    async def confirm_delete_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin_user.id:
            await interaction.response.send_message("❌ هذا الزر ليس لك!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(bot.DB_PATH) as db:
            await db.execute("DELETE FROM works")
            await db.execute("DELETE FROM drive_links")
            await db.execute("DELETE FROM reservations")
            await db.commit()
        await bot.log_admin_action(interaction.user.display_name, "حذف_جميع_أعمال", "حذف شامل مؤكد")
        log_embed = discord.Embed(title="🚨 حذف جميع الأعمال", color=discord.Color.dark_red())
        log_embed.description = f"• **الأدمن:** {interaction.user.mention}\n• **الإجراء:** مسح شامل لكافة الأعمال والروابط والحجوزات"
        await bot.send_admin_log(log_embed)
        await interaction.followup.send(content="🚨 **تم حذف كافة الأعمال والروابط والحجوزات!**", ephemeral=True)
        self.stop()

    @discord.ui.button(label="🔴 إلغاء", style=discord.ButtonStyle.secondary)
    async def cancel_delete_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ تم إلغاء الحذف.", ephemeral=True)
        self.stop()


@bot.tree.command(name="حذف_سجل_عضو", description="إدارة: مسح ملف عضو بالكامل")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو")
@app_commands.describe(member="اختر العضو المراد حذف سجله")
async def remove_member_profile(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("DELETE FROM members_profile WHERE user_id=?", (member.id,))
        await db.execute("DELETE FROM reservations WHERE user_id=?", (member.id,))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "حذف_سجل_عضو", f"مسح {member.display_name}")

    log_embed = discord.Embed(title="🗑️ حذف سجل عضو", color=discord.Color.dark_red(), timestamp=datetime.now())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention} (`{member.display_name}`)\n"
        f"• **الإجراء:** تم حذف الملف الشخصي وجميع الحجوزات"
    )
    await bot.send_admin_log(log_embed)

    await interaction.followup.send(
        content=f"✅ تم مسح سجل {member.mention} بالكامل.", ephemeral=True
    )


@bot.tree.command(name="تعديل_سجل_عضو", description="إدارة: تعديل فصول أو إنذارات عضو يدوياً")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو", warnings_count="عدد_الإنذارات", completed_chapters="الفصول_المنجزة", max_slots_capacity="سعة_الحجز")
@app_commands.describe(
    member="اختر العضو",
    warnings_count="أدخل عدد الإنذارات الجديد",
    completed_chapters="أدخل عدد الفصول المنجزة",
    max_slots_capacity="أدخل سعة الحجز الجديدة"
)
async def edit_member_records(
    interaction: discord.Interaction,
    member: discord.Member,
    warnings_count: int = None,
    completed_chapters: int = None,
    max_slots_capacity: int = None
):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)
        w = warnings_count if warnings_count is not None else p["warnings"]
        c = completed_chapters if completed_chapters is not None else p["completed"]
        s = max_slots_capacity if max_slots_capacity is not None else p["slots"]
        await db.execute(
            "UPDATE members_profile SET warnings=?, completed_chapters=?, max_slots=? WHERE user_id=?",
            (w, c, s, member.id)
        )
        await db.commit()

    await bot.log_admin_action(
        interaction.user.display_name, "تعديل_سجل_عضو",
        f"{member.display_name} → إنذارات: {w}، فصول: {c}، سعة: {s}"
    )

    log_embed = discord.Embed(title="✏️ تعديل سجل عضو", color=discord.Color.orange(), timestamp=datetime.now())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **إنذارات:** `{w}/3`\n"
        f"• **فصول منجزة:** `{c}`\n"
        f"• **سعة الحجز:** `{s}`"
    )
    await bot.send_admin_log(log_embed)

    await interaction.followup.send(
        content=f"✅ تم تعديل ملف {member.mention} ➔ إنذارات: `{w}` | فصول: `{c}` | سعة: `{s}`",
        ephemeral=True
    )


@bot.tree.command(name="استبعاد_عضو", description="إدارة: استبعاد عضو وتجميد رصيده عند آخر قيمة")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو", reason="السبب")
@app_commands.describe(member="اختر العضو", reason="اكتب سبب الاستبعاد")
async def exclude_member(interaction: discord.Interaction, member: discord.Member, reason: str):
    await interaction.response.defer(ephemeral=True)

    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)

        if p["is_excluded"] == 1:
            await interaction.followup.send(
                content=f"⚠️ العضو {member.mention} مستبعد مسبقاً.",
                ephemeral=True
            )
            return

        await db.execute(
            "UPDATE members_profile SET is_excluded=1, excluded_balance_snapshot=? WHERE user_id=?",
            (p["balance"], member.id)
        )
        await db.commit()

    try:
        dm_embed = discord.Embed(
            title="🚫 تم استبعادك من تيم كوكيز",
            color=discord.Color.dark_red()
        )
        dm_embed.description = (
            f"تم استبعادك من نظام الإنتاج.\n\n"
            f"📝 **السبب:** {reason}\n\n"
            f"💰 **رصيدك المجمد:** `{p['balance']:.2f}$`\n\n"
            f"تواصل مع الإدارة لمزيد من المعلومات."
        )
        await member.send(embed=dm_embed)
    except Exception:
        pass

    await bot.log_admin_action(
        interaction.user.display_name, "استبعاد_عضو",
        f"استبعاد {member.display_name} | السبب: {reason}"
    )

    log_embed = discord.Embed(title="🚫 استبعاد عضو", color=discord.Color.dark_red())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **السبب:** {reason}\n"
        f"• **الرصيد المجمد:** `{p['balance']:.2f}$`"
    )
    await bot.send_admin_log(log_embed)

    await interaction.followup.send(
        content=f"✅ تم استبعاد {member.mention}. رصيده مجمد عند `{p['balance']:.2f}$`.",
        ephemeral=True
    )


@bot.tree.command(name="الغاء_استبعاد_عضو", description="إدارة: إلغاء استبعاد عضو وإعادة تفعيله")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو")
@app_commands.describe(member="اختر العضو المراد إلغاء استبعاده")
async def unexclude_member(interaction: discord.Interaction, member: discord.Member):
    await interaction.response.defer(ephemeral=True)

    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)

        if p["is_excluded"] == 0:
            await interaction.followup.send(
                content=f"⚠️ العضو {member.mention} غير مستبعد أصلاً.",
                ephemeral=True
            )
            return

        await db.execute(
            "UPDATE members_profile SET is_excluded=0, excluded_balance_snapshot=0.0 WHERE user_id=?",
            (member.id,)
        )
        await db.commit()

    try:
        dm_embed = discord.Embed(
            title="✅ تم إلغاء استبعادك",
            color=discord.Color.green()
        )
        dm_embed.description = (
            f"تم إلغاء استبعادك وإعادة تفعيل حسابك في تيم كوكيز.\n\n"
            f"💰 **رصيدك الحالي:** `{p['balance']:.2f}$`\n\n"
            f"يمكنك الآن الحجز والعمل مجدداً! 🍪"
        )
        await member.send(embed=dm_embed)
    except Exception:
        pass

    await bot.log_admin_action(
        interaction.user.display_name, "الغاء_استبعاد_عضو",
        f"إلغاء استبعاد {member.display_name}"
    )

    log_embed = discord.Embed(title="✅ إلغاء استبعاد عضو", color=discord.Color.green())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **الرصيد المستعاد:** `{p['balance']:.2f}$`"
    )
    await bot.send_admin_log(log_embed)

    await interaction.followup.send(
        content=f"✅ تم إلغاء استبعاد {member.mention} وإعادة تفعيله.",
        ephemeral=True
    )


@bot.tree.command(name="تحذير_عضو", description="إدارة: إرسال تحذير رسمي لعضو مع تسجيله")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو", reason="السبب")
@app_commands.describe(member="اختر العضو", reason="اكتب سبب التحذير")
async def warn_member_officially(interaction: discord.Interaction, member: discord.Member, reason: str):
    await interaction.response.defer(ephemeral=True)

    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)
        new_warns = p["warnings"] + 1
        await db.execute(
            "UPDATE members_profile SET warnings=? WHERE user_id=?",
            (new_warns, member.id)
        )
        await db.commit()

    try:
        warn_embed = discord.Embed(
            title="⚠️ تحذير رسمي من إدارة تيم كوكيز",
            color=discord.Color.orange()
        )
        warn_embed.description = (
            f"تلقيت تحذيراً رسمياً من الإدارة.\n\n"
            f"📝 **سبب التحذير:** {reason}\n\n"
            f"⚠️ **إنذاراتك الحالية:** `{new_warns}/3`\n\n"
            f"تراكم 3 إنذارات يؤدي إلى حظر الحساب تلقائياً."
        )
        await member.send(embed=warn_embed)
        dm_result = "✅ تم إرسال التحذير للخاص"
    except discord.Forbidden:
        dm_result = "⚠️ فشل إرسال التحذير للخاص (الخاص مغلق)"

    await bot.log_admin_action(
        interaction.user.display_name, "تحذير_عضو",
        f"تحذير {member.display_name} | السبب: {reason} | إنذارات: {new_warns}/3"
    )

    log_embed = discord.Embed(title="⚠️ تحذير رسمي لعضو", color=discord.Color.orange())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **السبب:** {reason}\n"
        f"• **الإنذارات:** `{new_warns}/3`\n"
        f"• **حالة الإرسال:** {dm_result}"
    )
    await bot.send_admin_log(log_embed)

    await interaction.followup.send(
        content=f"✅ تم تحذير {member.mention}. إنذاراته: `{new_warns}/3`\n{dm_result}",
        ephemeral=True
    )


@bot.tree.command(name="بدون_حجوزات", description="إدارة: عرض قائمة الأعضاء المسجلين بدون حجوزات نشطة")
@app_commands.checks.has_permissions(administrator=True)
async def members_without_reservations(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("""
            SELECT mp.user_id, mp.user_name, mp.completed_chapters, mp.warnings, mp.is_excluded
            FROM members_profile mp
            WHERE mp.user_id NOT IN (
                SELECT DISTINCT user_id FROM reservations
            )
            ORDER BY mp.completed_chapters DESC
        """) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.followup.send(
            content="✅ جميع الأعضاء المسجلين لديهم حجوزات نشطة حالياً.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"📋 الأعضاء بدون حجوزات نشطة ({len(rows)} عضو)",
        color=discord.Color.orange()
    )
    desc = ""
    for idx, (uid, uname, completed, warnings, is_excluded) in enumerate(rows, 1):
        excluded_tag = " 🚫" if is_excluded else ""
        desc += f"{idx}. <@{uid}> (`{uname}`){excluded_tag} | فصول: `{completed}` | إنذارات: `{warnings}/3`\n"
        if idx == 25:
            desc += f"... و {len(rows) - 25} أعضاء آخرين"
            break

    embed.description = desc
    embed.set_footer(text=f"إجمالي: {len(rows)} عضو بدون حجوزات")
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="تغير_أسعار", description="إدارة: تعديل سعر تخصص معين")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(role_name="اسم_التخصص", new_price="السعر_الجديد")
@app_commands.describe(role_name="اختر التخصص", new_price="أدخل السعر الجديد بالدولار")
@app_commands.autocomplete(role_name=autocomplete_all_roles)
async def change_role_payout_price(interaction: discord.Interaction, role_name: str, new_price: float):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT role_name FROM roles_config WHERE role_name=?", (role_name,)) as cursor:
            if not await cursor.fetchone():
                await interaction.followup.send(
                    content="❌ التخصص غير موجود. أضفه عبر `/اضافة_تخصص`", ephemeral=True
                )
                return
        await db.execute("UPDATE roles_config SET price=? WHERE role_name=?", (new_price, role_name))
        await db.commit()

    await bot.log_admin_action(interaction.user.display_name, "تغير_أسعار", f"{role_name} → {new_price}$")
    await interaction.followup.send(
        content=f"✅ تم تعديل مكافأة **{role_name}** إلى **{new_price:.2f}$** للفصل.", ephemeral=True
    )


@bot.tree.command(name="اضافة_تخصص", description="إدارة: إضافة تخصص جديد بالسيستم")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(role_name="اسم_التخصص", price="السعر")
@app_commands.describe(role_name="اكتب اسم التخصص الجديد", price="أدخل السعر بالدولار")
async def add_new_production_role(interaction: discord.Interaction, role_name: str, price: float):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO roles_config (role_name, price, is_enabled) VALUES (?, ?, 1)",
            (role_name, price)
        )
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "اضافة_تخصص", f"{role_name} بسعر {price}$")
    await interaction.followup.send(
        content=f"✅ تم إضافة التخصص **{role_name}** بسعر **{price:.2f}$** للفصل.", ephemeral=True
    )


@bot.tree.command(name="حذف_تخصص", description="إدارة: مسح تخصص نهائياً")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(role_name="اسم_التخصص")
@app_commands.describe(role_name="اختر التخصص المراد حذفه")
@app_commands.autocomplete(role_name=autocomplete_all_roles)
async def delete_production_role(interaction: discord.Interaction, role_name: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("DELETE FROM roles_config WHERE role_name=?", (role_name,))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "حذف_تخصص", f"حذف {role_name}")
    await interaction.followup.send(content=f"✅ تم حذف التخصص **{role_name}**.", ephemeral=True)


@bot.tree.command(name="تفعيل_تخصص", description="إدارة: تفعيل تخصص في قوائم الحجز")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(role_name="اسم_التخصص")
@app_commands.describe(role_name="اختر التخصص المراد تفعيله")
@app_commands.autocomplete(role_name=autocomplete_all_roles)
async def enable_production_role(interaction: discord.Interaction, role_name: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("UPDATE roles_config SET is_enabled=1 WHERE role_name=?", (role_name,))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "تفعيل_تخصص", role_name)
    await interaction.followup.send(content=f"✅ تم تفعيل التخصص **{role_name}**.", ephemeral=True)


@bot.tree.command(name="تعطيل_تخصص", description="إدارة: تعطيل تخصص مؤقتاً")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(role_name="اسم_التخصص")
@app_commands.describe(role_name="اختر التخصص المراد تعطيله")
@app_commands.autocomplete(role_name=autocomplete_all_roles)
async def disable_production_role(interaction: discord.Interaction, role_name: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("UPDATE roles_config SET is_enabled=0 WHERE role_name=?", (role_name,))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "تعطيل_تخصص", role_name)
    await interaction.followup.send(content=f"✅ تم تعطيل التخصص **{role_name}** مؤقتاً.", ephemeral=True)


@bot.tree.command(name="تحديد_موعد_دفع", description="إدارة: تدوين موعد توزيع الرواتب")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(date_text="تاريخ_الدفع")
@app_commands.describe(date_text="اكتب موعد الدفع (مثال: كل 1 من الشهر)")
async def set_pay_day_notice(interaction: discord.Interaction, date_text: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("UPDATE settings SET value=? WHERE key='pay_day_notice'", (date_text,))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "تحديد_موعد_دفع", date_text)
    await interaction.followup.send(content=f"✅ تم حفظ موعد الدفع: **{date_text}**.", ephemeral=True)


@bot.tree.command(name="مكافأة", description="إدارة: إضافة أرباح استثنائية لعضو")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو", amount="المبلغ", reason="السبب")
@app_commands.describe(member="اختر العضو", amount="أدخل المبلغ بالدولار", reason="اكتب سبب المكافأة")
async def admin_bonus_reward(interaction: discord.Interaction, member: discord.Member, amount: float, reason: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)
        new_bal = p["balance"] + amount
        await db.execute("UPDATE members_profile SET balance=? WHERE user_id=?", (new_bal, member.id))
        await db.commit()

    await bot.log_admin_action(interaction.user.display_name, "مكافأة", f"{member.display_name} +{amount}$")
    log_emb = discord.Embed(title="🎁 مكافأة مالية استثنائية", color=discord.Color.green())
    log_emb.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **المبلغ:** `+{amount:.2f}$`\n"
        f"• **السبب:** {reason}\n"
        f"• **الرصيد الحالي:** `{new_bal:.2f}$`"
    )
    await bot.send_admin_log(log_emb)

    try:
        bonus_dm = discord.Embed(title="🎁 مكافأة مالية!", color=discord.Color.green())
        bonus_dm.description = (
            f"تم إضافة مكافأة لمحفظتك:\n"
            f"💰 **المبلغ:** `+{amount:.2f}$`\n"
            f"📝 **السبب:** {reason}\n"
            f"💼 **رصيدك الحالي:** `{new_bal:.2f}$`"
        )
        await member.send(embed=bonus_dm)
    except Exception:
        pass

    await interaction.followup.send(
        content=f"✅ تم صرف المكافأة. الرصيد الحالي: `{new_bal:.2f}$`", ephemeral=True
    )


@bot.tree.command(name="خصم", description="إدارة: خصم مالي من محفظة عضو")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو", amount="المبلغ", reason="السبب")
@app_commands.describe(member="اختر العضو", amount="أدخل المبلغ بالدولار", reason="اكتب سبب الخصم")
async def admin_deduct_fine(interaction: discord.Interaction, member: discord.Member, amount: float, reason: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)
        new_bal = max(0.0, p["balance"] - amount)
        await db.execute("UPDATE members_profile SET balance=? WHERE user_id=?", (new_bal, member.id))
        await db.commit()

    await bot.log_admin_action(interaction.user.display_name, "خصم", f"{member.display_name} -{amount}$")
    log_emb = discord.Embed(title="🚨 خصم مالي مباشر", color=discord.Color.red())
    log_emb.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **المبلغ:** `-{amount:.2f}$`\n"
        f"• **السبب:** {reason}\n"
        f"• **الرصيد المتبقي:** `{new_bal:.2f}$`"
    )
    await bot.send_admin_log(log_emb)

    try:
        deduct_dm = discord.Embed(title="🚨 إشعار خصم مالي", color=discord.Color.red())
        deduct_dm.description = (
            f"تم خصم مبلغ من محفظتك:\n"
            f"💸 **المبلغ:** `-{amount:.2f}$`\n"
            f"📝 **السبب:** {reason}\n"
            f"💼 **رصيدك المتبقي:** `{new_bal:.2f}$`"
        )
        await member.send(embed=deduct_dm)
    except Exception:
        pass

    await interaction.followup.send(
        content=f"✅ تم الخصم. الرصيد الحالي: `{new_bal:.2f}$`", ephemeral=True
    )


@bot.tree.command(name="تقرير_دفع", description="إدارة: استخراج لائحة المستحقات الصافية")
@app_commands.checks.has_permissions(administrator=True)
async def export_payment_report(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT user_name, balance, is_excluded FROM members_profile WHERE balance > 0 ORDER BY balance DESC"
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.followup.send(content="📭 لا توجد مستحقات معلقة.", ephemeral=True)
        return

    report = "📊 كشف الرواتب والمستحقات | تيم كوكيز\n"
    report += "=" * 50 + "\n"
    total_all = 0.0
    for idx, (uname, bal, is_excluded) in enumerate(rows, 1):
        excluded_note = " [مستبعد - محجوب]" if is_excluded else ""
        report += f"{idx}. {uname}{excluded_note} | {bal:.2f}$\n"
        total_all += bal
    report += "=" * 50 + "\n"
    report += f"💰 الإجمالي: {total_all:.2f}$"

    file_stream = io.BytesIO(report.encode('utf-8'))
    discord_file = discord.File(fp=file_stream, filename=f"كشف_الدفع_{datetime.now().strftime('%Y-%m-%d')}.txt")
    await interaction.followup.send(content="📝 **كشف الدفع الشامل:**", file=discord_file, ephemeral=True)


@bot.tree.command(name="تقرير_أسبوعي", description="إدارة: التقرير الإنتاجي الأسبوعي")
@app_commands.checks.has_permissions(administrator=True)
async def weekly_production_report(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT user_name, completed_chapters FROM members_profile WHERE completed_chapters > 0 ORDER BY completed_chapters DESC LIMIT 5"
        ) as c1:
            top_knights = await c1.fetchall()
        async with db.execute(
            "SELECT name, current_chapter FROM works WHERE is_active=1 ORDER BY current_chapter DESC LIMIT 5"
        ) as c2:
            top_works = await c2.fetchall()
        async with db.execute(
            "SELECT COUNT(*) FROM chapter_submissions WHERE status='approved'"
        ) as c3:
            total_approved = (await c3.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM chapter_submissions WHERE status='pending_review'"
        ) as c4:
            total_pending = (await c4.fetchone())[0]

    embed = discord.Embed(
        title="📊 التقرير الإنتاجي الأسبوعي | تيم كوكيز",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    knights_text = "\n".join(
        f"🥇 {uname} ➔ `{count}` فصل" for uname, count in top_knights
    ) or "لا توجد سجلات."
    works_text = "\n".join(
        f"📚 **{wname}** ➔ فصل `{chap}`" for wname, chap in top_works
    ) or "لا توجد أعمال نشطة."

    embed.add_field(name="⚔️ فرسان الإنتاج الأعلى:", value=knights_text, inline=False)
    embed.add_field(name="📈 الأعمال الأكثر تقدماً:", value=works_text, inline=False)
    embed.add_field(name="✅ إجمالي الفصول المقبولة", value=f"`{total_approved}`", inline=True)
    embed.add_field(name="⏳ بانتظار المراجعة", value=f"`{total_pending}`", inline=True)
    embed.set_footer(text="قسم مانهوا أزورا")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="سجل_عرض_آخر_عشرين_امر", description="إدارة: آخر 20 عملية إدارية")
@app_commands.checks.has_permissions(administrator=True)
async def view_recent_admin_logs(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT admin_name, command_name, details, timestamp FROM admin_logs ORDER BY id DESC LIMIT 20"
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.followup.send(content="📭 لا توجد عمليات مسجلة.", ephemeral=True)
        return

    embed = discord.Embed(title="📋 آخر 20 عملية إدارية", color=discord.Color.orange())
    desc = ""
    for idx, (aname, cname, details, ts) in enumerate(rows, 1):
        dt = datetime.fromisoformat(ts).strftime('%m/%d %H:%M')
        desc += f"**{idx}. [{dt}] {aname}**\n   ➔ `{cname}` | {details}\n"
    embed.description = desc
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="أدمن_استيراد_بيانات", description="إدارة: استيراد بيانات من ملف JSON")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(file="ملف_البيانات")
@app_commands.describe(file="ارفع ملف JSON للاستيراد")
async def admin_manual_import(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    if not file.filename.endswith('.json'):
        await interaction.followup.send(content="❌ يرجى إرفاق ملف `.json` فقط.", ephemeral=True)
        return
    try:
        file_bytes = await file.read()
        data = json.loads(file_bytes.decode('utf-8'))
        unique_works = {}

        async with aiosqlite.connect(bot.DB_PATH) as db:
            for user_id_str, history in data.items():
                user_id = int(user_id_str)
                last_username = "عضو في تيم كوكيز"
                total_balance = 0.0
                completed_count = 0
                warnings_count = 0

                for entry in history:
                    uname = entry.get("اسم_المستخدم", entry.get("username", "عضو في تيم كوكيز"))
                    last_username = uname
                    work_name = entry.get("اسم_العمل", entry.get("work_name"))
                    chapter_str = entry.get("الفصل", entry.get("chapter", "1"))
                    role = entry.get("التخصص", entry.get("work_type", ""))
                    total_val = float(entry.get("المبلغ", entry.get("total", 0.0)))

                    if (work_name and work_name != "نظام المكافآت والخصومات"
                            and role not in ["مكافأة", "خصم", "ملخص البروفايل"]):
                        try:
                            chap_num = int(''.join(filter(str.isdigit, chapter_str)))
                        except ValueError:
                            chap_num = 1
                        if work_name not in unique_works or chap_num > unique_works[work_name]:
                            unique_works[work_name] = chap_num
                        total_balance += total_val
                        completed_count += 1
                    elif work_name == "نظام المكافآت والخصومات":
                        notes_str = entry.get("الملاحظات", entry.get("notes", ""))
                        if "إنذارات نشطة" in notes_str:
                            try:
                                warnings_count = int(notes_str.split("إنذارات نشطة:")[1].split("|")[0].strip())
                                completed_count = int(notes_str.split("فصول مكتملة:")[1].strip())
                            except Exception:
                                pass
                            total_balance = total_val
                        else:
                            total_balance += total_val

                await db.execute('''
                    INSERT INTO members_profile (user_id, user_name, balance, warnings, completed_chapters, max_slots)
                    VALUES (?, ?, ?, ?, ?, 3)
                    ON CONFLICT(user_id) DO UPDATE SET
                        user_name=excluded.user_name,
                        balance=excluded.balance,
                        warnings=excluded.warnings,
                        completed_chapters=excluded.completed_chapters
                ''', (user_id, last_username, total_balance, warnings_count, completed_count))

            for name, current_chap in unique_works.items():
                await db.execute('''
                    INSERT INTO works (name, current_chapter, is_active, required_roles) VALUES (?, ?, 1, 3)
                    ON CONFLICT(name) DO UPDATE SET current_chapter=MAX(current_chapter, excluded.current_chapter)
                ''', (name, current_chap))
            await db.commit()

        await bot.log_admin_action(interaction.user.display_name, "استيراد_بيانات", file.filename)

        log_embed = discord.Embed(title="📥 استيراد بيانات", color=discord.Color.blue(), timestamp=datetime.now())
        log_embed.description = (
            f"• **الأدمن:** {interaction.user.mention}\n"
            f"• **الملف:** `{file.filename}`\n"
            f"• **الأعضاء المستوردون:** `{len(data)}` عضو\n"
            f"• **الأعمال المستوردة:** `{len(unique_works)}` عمل"
        )
        await bot.send_admin_log(log_embed)

        await interaction.followup.send(
            content=f"✅ **تم استيراد البيانات بنجاح!**\n• الأعضاء: `{len(data)}`\n• الأعمال: `{len(unique_works)}`",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(content=f"❌ خطأ أثناء قراءة الملف: {e}", ephemeral=True)


@bot.tree.command(name="أدمن_اكتمال_عمل", description="إدارة: إخفاء مانهوا مكتملة من قائمة الحجوزات")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(work_name="اسم_العمل")
@app_commands.describe(work_name="اختر المانهوا المكتملة")
@app_commands.autocomplete(work_name=autocomplete_all_works)
async def admin_hide_work(interaction: discord.Interaction, work_name: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT is_active FROM works WHERE name=?", (work_name,)) as cursor:
            if not await cursor.fetchone():
                await interaction.followup.send(content="❌ المانهوا غير موجودة.", ephemeral=True)
                return
        await db.execute("UPDATE works SET is_active=0 WHERE name=?", (work_name,))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "اكتمال_عمل", f"إخفاء {work_name}")
    await interaction.followup.send(
        content=f"✅ **تم تحويل ({work_name}) للأعمال المكتملة وإخفاؤها.**", ephemeral=True
    )


@bot.tree.command(name="أدمن_إرجاع_عمل", description="إدارة: إعادة تنشيط مانهوا مكتملة")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(work_name="اسم_العمل")
@app_commands.describe(work_name="اختر المانهوا المراد إعادة تنشيطها")
@app_commands.autocomplete(work_name=autocomplete_all_works)
async def admin_unhide_work(interaction: discord.Interaction, work_name: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT is_active FROM works WHERE name=?", (work_name,)) as cursor:
            if not await cursor.fetchone():
                await interaction.followup.send(content="❌ المانهوا غير موجودة.", ephemeral=True)
                return
        await db.execute("UPDATE works SET is_active=1 WHERE name=?", (work_name,))
        await db.commit()
    await bot.log_admin_action(interaction.user.display_name, "إرجاع_عمل", f"إظهار {work_name}")
    await interaction.followup.send(
        content=f"✅ **تمت إعادة تنشيط ({work_name}) في قائمة الأعمال.**", ephemeral=True
    )


@bot.tree.command(name="اعلان_دفعات", description="إدارة: الإعلان عن دفعة فصول جديدة وإدخال روابطها")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(
    work_name="اسم_العمل",
    role="التخصص",
    amount_of_chapters="عدد_الفصول",
    drive_url1="رابط_الدرايف_1",
    drive_url2="رابط_الدرايف_2",
    drive_url3="رابط_الدرايف_3",
    drive_url4="رابط_الدرايف_4"
)
@app_commands.describe(
    work_name="اختر اسم المانهوا",
    role="اختر التخصص",
    amount_of_chapters="أدخل عدد الفصول في الدفعة",
    drive_url1="أدخل الرابط الأول",
    drive_url2="أدخل الرابط الثاني (اختياري)",
    drive_url3="أدخل الرابط الثالث (اختياري)",
    drive_url4="أدخل الرابط الرابع (اختياري)"
)
@app_commands.autocomplete(work_name=autocomplete_all_works, role=autocomplete_all_roles)
async def admin_announce_batch(
    interaction: discord.Interaction,
    work_name: str,
    role: str,
    amount_of_chapters: int,
    drive_url1: str,
    drive_url2: str = None,
    drive_url3: str = None,
    drive_url4: str = None
):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("SELECT is_enabled FROM roles_config WHERE role_name=?", (role,)) as r_cur:
            if not await r_cur.fetchone():
                await interaction.followup.send(content="❌ التخصص غير موجود.", ephemeral=True)
                return

        async with db.execute("SELECT current_chapter FROM works WHERE name=?", (work_name,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            await db.execute(
                "INSERT OR IGNORE INTO works (name, current_chapter, is_active, required_roles) VALUES (?, 1, 1, 3)",
                (work_name,)
            )
            start_chap = 1
        else:
            start_chap = row[0]

        all_urls = [drive_url1, drive_url2, drive_url3, drive_url4]
        for i in range(amount_of_chapters):
            target_chap = start_chap + i
            chapter_url = all_urls[i] if i < len(all_urls) and all_urls[i] else drive_url1

            await db.execute(
                """INSERT INTO drive_links
                (work_name, chapter_num, role, drive_url1, is_booked, is_frozen)
                VALUES (?, ?, ?, ?, 0, 0)
                ON CONFLICT(work_name, chapter_num, role)
                DO UPDATE SET drive_url1=?, is_booked=0, is_frozen=0""",
                (work_name, target_chap, role, chapter_url, chapter_url)
            )
        await db.commit()

    commands_channel = bot.get_channel(bot.COMMANDS_CHANNEL_ID)
    if commands_channel:
        ann_embed = discord.Embed(
            title="📢 دفعة فصول جديدة متاحة للحجز! | تيم كوكيز",
            color=discord.Color.green()
        )
        ann_embed.description = (
            f"🚀 دفعة أعمال جديدة لمانهوا: **{work_name}**\n\n"
            f"• **التخصص المطلوب:** `{role}`\n"
            f"• **الفصول الجاهزة:** `{amount_of_chapters} فصول`\n"
            f"• **النطاق:** فصل {start_chap} ← فصل {start_chap + amount_of_chapters - 1}\n\n"
            f"👇 اكتب `/حجز_عمل` الآن للبدء!"
        )
        try:
            await commands_channel.send(content="@everyone", embed=ann_embed)
        except Exception:
            pass

    await bot.log_admin_action(
        interaction.user.display_name, "اعلان_دفعات",
        f"{work_name} ({amount_of_chapters} فصول) تخصص {role}"
    )
    await interaction.followup.send(
        content=f"✅ **تم إدخال الدفعة بنجاح!**", ephemeral=True
    )


@bot.tree.command(name="حجز_عمل_لغيري", description="إدارة: إسناد حجز لعضو آخر يدوياً")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو")
@app_commands.describe(member="اختر العضو المراد إسناد الحجز له")
async def book_for_someone(interaction: discord.Interaction, member: discord.Member):
    if member.bot:
        await interaction.response.send_message("❌ لا يمكن إسناد مهام للبوتات!", ephemeral=True)
        return
    await interaction.response.send_message(
        content=f"⚙️ **لوحة المسؤول:** إسناد عمل للعضو: {member.mention}",
        ephemeral=False
    )
    msg = await interaction.original_response()
    await msg.edit(view=DirectBookLauncher(interaction.user, member, msg.id))


@bot.tree.command(name="سحب_حجز_يدوي", description="إدارة: إلغاء حجز من عضو يدوياً")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو", work_name="اسم_العمل", chapter_num="رقم_الفصل", role="التخصص")
@app_commands.describe(
    member="اختر العضو",
    work_name="اختر اسم المانهوا",
    chapter_num="أدخل رقم الفصل",
    role="اختر التخصص"
)
@app_commands.autocomplete(work_name=autocomplete_all_works, role=autocomplete_all_roles)
async def admin_force_remove_res(
    interaction: discord.Interaction,
    member: discord.Member,
    work_name: str,
    chapter_num: int,
    role: str
):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
            (member.id, work_name, chapter_num, role)
        ) as cursor:
            if not await cursor.fetchone():
                await interaction.followup.send(content="❌ الحجز غير موجود.", ephemeral=True)
                return
        await db.execute(
            "DELETE FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
            (member.id, work_name, chapter_num, role)
        )
        await db.execute(
            "UPDATE drive_links SET is_booked=0, is_frozen=0 WHERE work_name=? AND chapter_num=? AND role=?",
            (work_name, chapter_num, role)
        )
        await db.commit()

    # إشعار العضو
    dm_note = ""
    try:
        dm_embed = discord.Embed(title="🚨 تم سحب حجزك يدوياً", color=discord.Color.red())
        dm_embed.description = (
            f"تم سحب حجزك من قِبَل الإدارة:\n"
            f"📚 **المانهوا:** `{work_name}` فصل `{chapter_num}` تخصص `{role}`\n\n"
            f"تواصل مع الإدارة لمزيد من المعلومات."
        )
        await member.send(embed=dm_embed)
        dm_note = "✅ تم إشعار العضو بالخاص"
    except discord.Forbidden:
        dm_note = "⚠️ فشل إرسال إشعار للعضو (الخاص مغلق)"

    await bot.log_admin_action(
        interaction.user.display_name, "سحب_حجز_يدوي",
        f"سحب {work_name} ف{chapter_num} من {member.display_name}"
    )

    log_embed = discord.Embed(title="🚨 سحب حجز يدوي", color=discord.Color.red())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **الحجز:** `{work_name}` (فصل {chapter_num}) تخصص `{role}`\n"
        f"• **الإشعار:** {dm_note}"
    )
    await bot.send_admin_log(log_embed)
    await interaction.followup.send(content=f"✅ **تم سحب الحجز بنجاح!**\n{dm_note}", ephemeral=True)


@bot.tree.command(name="تعديل_رصيد", description="إدارة: تعديل رصيد عضو في المحفظة")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو", amount="المبلغ", reason="السبب")
@app_commands.describe(member="اختر العضو", amount="أدخل المبلغ (موجب للإضافة، سالب للخصم)", reason="اكتب سبب التعديل")
async def admin_modify_balance(interaction: discord.Interaction, member: discord.Member, amount: float, reason: str):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)
        new_bal = max(0.0, p["balance"] + amount)
        await db.execute("UPDATE members_profile SET balance=? WHERE user_id=?", (new_bal, member.id))
        await db.commit()
    await bot.log_admin_action(
        interaction.user.display_name, "تعديل_رصيد", f"{member.display_name} → {amount}$"
    )

    log_emb = discord.Embed(title="💵 تعديل رصيد عضو", color=discord.Color.blue(), timestamp=datetime.now())
    log_emb.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **التعديل:** `{'+' if amount >= 0 else ''}{amount:.2f}$`\n"
        f"• **السبب:** {reason}\n"
        f"• **الرصيد الجديد:** `{new_bal:.2f}$`"
    )
    await bot.send_admin_log(log_emb)

    try:
        dm_emb = discord.Embed(title="💵 تعديل في رصيدك", color=discord.Color.blue())
        dm_emb.description = (
            f"تم تعديل رصيدك من قِبَل الإدارة:\n"
            f"• **التعديل:** `{'+' if amount >= 0 else ''}{amount:.2f}$`\n"
            f"• **السبب:** {reason}\n"
            f"• **رصيدك الحالي:** `{new_bal:.2f}$`"
        )
        await member.send(embed=dm_emb)
    except Exception:
        pass

    await interaction.followup.send(
        content=f"✅ **تم تعديل المحفظة. الرصيد الجديد: {new_bal:.2f}$**", ephemeral=True
    )


@bot.tree.command(name="الدفعات_المعلقة", description="إدارة: استعراض الفصول المعلقة في المخزن")
@app_commands.checks.has_permissions(administrator=True)
async def admin_view_pending_batches(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT work_name, chapter_num, role FROM drive_links WHERE is_booked=0 AND is_frozen=0 ORDER BY work_name ASC, chapter_num ASC"
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.followup.send(content="📭 المخزن فارغ.", ephemeral=True)
        return

    embed = discord.Embed(title="📋 الدفعات المعلقة في المخزن:", color=discord.Color.blue())
    text = ""
    for idx, (work, chap, role) in enumerate(rows[:30], 1):
        text += f"{idx}. **{work}** ➔ فصل `{chap}` تخصص [{role}]\n"
    embed.description = text
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="تصفير_الشهر", description="إدارة: تصفير الأرصدة والفصول لبدء دورة جديدة")
@app_commands.checks.has_permissions(administrator=True)
async def admin_reset_monthly_cycle(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚠️ تأكيد تصفير الشهر",
        color=discord.Color.red()
    )
    embed.description = (
        "**هذا الإجراء سيمسح:**\n"
        "• جميع أرصدة الأعضاء → 0.00$\n"
        "• جميع عدادات الفصول المكتملة → 0\n\n"
        "⛔ **لا يمكن التراجع عن هذا الإجراء!**\n"
        "تأكد أنك أجريت `/تصدير_البيانات` و`/تقرير_دفع` قبل المتابعة."
    )
    view = ConfirmResetView(interaction.user)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ConfirmResetView(discord.ui.View):
    def __init__(self, admin_user):
        super().__init__(timeout=30)
        self.admin_user = admin_user

    @discord.ui.button(label="✅ نعم، صفّر الشهر", style=discord.ButtonStyle.danger)
    async def confirm_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.admin_user.id:
            await interaction.response.send_message("❌ هذا الزر ليس لك!", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(bot.DB_PATH) as db:
            await db.execute("UPDATE members_profile SET balance=0.0, completed_chapters=0")
            await db.commit()
        await bot.log_admin_action(interaction.user.display_name, "تصفير_الشهر", "تصفير كلي مؤكد")
        log_embed = discord.Embed(title="🔄 تصفير شهري", color=discord.Color.red())
        log_embed.description = f"• **الأدمن:** {interaction.user.mention}\n• **الإجراء:** تصفير كل الأرصدة والفصول"
        await bot.send_admin_log(log_embed)
        await interaction.followup.send(content="✅ **تم تصفير الأرصدة لدورة جديدة!**", ephemeral=True)
        self.stop()

    @discord.ui.button(label="🔴 إلغاء", style=discord.ButtonStyle.secondary)
    async def cancel_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ تم إلغاء التصفير.", ephemeral=True)
        self.stop()


@bot.tree.command(name="تصدير_البيانات", description="إدارة: توليد ملف JSON احتياطي")
@app_commands.checks.has_permissions(administrator=True)
async def export_to_json(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, user_name, balance, completed_chapters, warnings FROM members_profile"
        ) as cursor:
            profiles = await cursor.fetchall()
        async with db.execute(
            "SELECT user_id, work_name, chapter_num, role, time_booked FROM reservations"
        ) as cursor:
            reservations = await cursor.fetchall()
        async with db.execute(
            "SELECT role_name, price FROM roles_config"
        ) as cursor:
            roles_prices = {r[0]: r[1] for r in await cursor.fetchall()}

    backup_data = {}
    for uid, uname, balance, completed, warnings in profiles:
        user_key = str(uid)
        backup_data[user_key] = []
        user_res = [r for r in reservations if r[0] == uid]
        if user_res:
            for _, work, chap, role, b_time in user_res:
                actual_price = roles_prices.get(role, 0.25)
                backup_data[user_key].append({
                    "اسم_العمل": work,
                    "الفصل": str(chap),
                    "التخصص": role,
                    "المبلغ": actual_price,
                    "الملاحظات": "حجز نشط",
                    "التوقيت": b_time,
                    "اسم_المستخدم": uname,
                    "أضيف_بواسطة": str(interaction.user.id)
                })
        else:
            backup_data[user_key].append({
                "اسم_العمل": "نظام المكافآت والخصومات",
                "الفصل": "رصيد تراكمي صافي",
                "التخصص": "ملخص البروفايل",
                "المبلغ": balance,
                "الملاحظات": f"إنذارات نشطة: {warnings} | فصول مكتملة بالشهر: {completed}",
                "التوقيت": datetime.now().isoformat(),
                "اسم_المستخدم": uname,
                "أضيف_بواسطة": str(interaction.user.id)
            })

    json_string = json.dumps(backup_data, ensure_ascii=False, indent=2)
    file_stream = io.BytesIO(json_string.encode('utf-8'))
    discord_file = discord.File(
        fp=file_stream,
        filename=f"نسخة_احتياطية_{datetime.now().strftime('%Y-%m-%d')}.json"
    )
    await interaction.followup.send(content="📦 **ملف الباك أب جاهز!**", file=discord_file, ephemeral=True)


@bot.tree.command(name="مستجدات_نهاية_الشهر", description="إدارة: التقرير المالي والإنتاجي الختامي")
@app_commands.checks.has_permissions(administrator=True)
async def monthly_report(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, user_name, balance, completed_chapters, is_excluded FROM members_profile ORDER BY completed_chapters DESC"
        ) as cursor:
            all_profiles = await cursor.fetchall()

    if not all_profiles:
        await interaction.followup.send(content="📭 قاعدة البيانات فارغة.")
        return

    embed = discord.Embed(
        title="📊 التقرير الختامي | تيم كوكيز",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    total_payout, total_chapters, leaderboard = 0.0, 0, ""
    for index, (uid, uname, balance, completed, is_excluded) in enumerate(all_profiles, 1):
        total_payout += balance
        total_chapters += completed
        medal = "👑" if index == 1 else "🥈" if index == 2 else "🥉" if index == 3 else "•"
        excluded_tag = " 🚫" if is_excluded else ""
        leaderboard += (
            f"{medal} **{uname}**{excluded_tag} (<@{uid}>)\n"
            f"   ➔ فصوله: `{completed}` | مستحقاته: `{balance:.2f}$`\n"
        )

    embed.description = f"### 🏆 ترتيب الفرسان:\n\n{leaderboard}"
    embed.add_field(name="💰 إجمالي المستحقات", value=f"**{total_payout:.2f}$**", inline=True)
    embed.add_field(name="📚 إجمالي الفصول", value=f"**{total_chapters} فصل**", inline=True)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="الغاء_الانذارات", description="إدارة: إلغاء إنذارات عضو")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(member="العضو", count_to_remove="عدد_الإنذارات_المراد_إلغاؤها")
@app_commands.describe(member="اختر العضو", count_to_remove="أدخل عدد الإنذارات المراد إلغاؤها")
async def remove_warnings(interaction: discord.Interaction, member: discord.Member, count_to_remove: int):
    async with aiosqlite.connect(bot.DB_PATH) as db:
        p = await get_or_create_profile(db, member.id, member.display_name)
        new_warns = max(0, p["warnings"] - count_to_remove)
        await db.execute("UPDATE members_profile SET warnings=? WHERE user_id=?", (new_warns, member.id))
        await db.commit()
    await bot.log_admin_action(
        interaction.user.display_name, "الغاء_الانذارات",
        f"مسح {count_to_remove} إنذار عن {member.display_name}"
    )

    log_embed = discord.Embed(title="✅ إلغاء إنذارات عضو", color=discord.Color.green(), timestamp=datetime.now())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **العضو:** {member.mention}\n"
        f"• **الإنذارات المُلغاة:** `{count_to_remove}`\n"
        f"• **الإنذارات الحالية:** `{new_warns}/3`"
    )
    await bot.send_admin_log(log_embed)

    await interaction.response.send_message(
        f"✅ إنذارات {member.mention} أصبحت: **{new_warns}/3**", ephemeral=True
    )


@bot.tree.command(name="تعديل_مهلة_رفع_روابط", description="إدارة: تعديل مهلة رفع الروابط بعد إكمال الفصل")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(hours="المهلة_بالساعات")
@app_commands.describe(hours="أدخل المهلة الجديدة بالساعات")
async def set_submission_deadline(interaction: discord.Interaction, hours: int):
    await interaction.response.defer(ephemeral=True)
    if hours < 1:
        await interaction.followup.send(content="❌ المهلة يجب أن تكون ساعة واحدة على الأقل.", ephemeral=True)
        return
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("UPDATE settings SET value=? WHERE key='submission_deadline_hours'", (str(hours),))
        await db.commit()
    await bot.log_admin_action(
        interaction.user.display_name, "تعديل_مهلة_رفع_روابط", f"المهلة → {hours} ساعة"
    )
    await interaction.followup.send(
        content=f"✅ تم تعديل مهلة رفع الروابط إلى **{hours} ساعة**.", ephemeral=True
    )


@bot.tree.command(name="تعديل_محاولات_تعديل", description="إدارة: تعديل الحد الأقصى لمحاولات التعديل قبل الرفض النهائي")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(max_attempts="أقصى_محاولات")
@app_commands.describe(max_attempts="أدخل الحد الأقصى لمحاولات التعديل")
async def set_max_edit_attempts(interaction: discord.Interaction, max_attempts: int):
    await interaction.response.defer(ephemeral=True)
    if max_attempts < 1:
        await interaction.followup.send(content="❌ يجب أن تكون محاولة واحدة على الأقل.", ephemeral=True)
        return
    async with aiosqlite.connect(bot.DB_PATH) as db:
        await db.execute("UPDATE settings SET value=? WHERE key='max_edit_attempts'", (str(max_attempts),))
        await db.commit()
    await bot.log_admin_action(
        interaction.user.display_name, "تعديل_محاولات_تعديل", f"أقصى محاولات → {max_attempts}"
    )
    await interaction.followup.send(
        content=f"✅ تم تعديل الحد الأقصى لمحاولات التعديل إلى **{max_attempts}**.", ephemeral=True
    )


# ==========================================
# ⚙️ نظام الأوامر المخصصة
# ==========================================

class AddCommandModal(discord.ui.Modal, title="إضافة أمر مخصص جديد"):
    اسم_الأمر = discord.ui.TextInput(
        label="اسم الأمر (بدون / وبدون مسافات)",
        placeholder="مثال: القواعد أو التعليمات",
        style=discord.TextStyle.short,
        required=True,
        max_length=32
    )
    نص_الرد = discord.ui.TextInput(
        label="نص الرد",
        placeholder="اكتب الرد الذي سيظهر عند استخدام الأمر...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        raw_name = self.اسم_الأمر.value.strip()
        cmd_name = raw_name.replace(" ", "_").lower()
        response_text = self.نص_الرد.value.strip()

        existing_commands = [cmd.name for cmd in bot.tree.get_commands()]
        if cmd_name in existing_commands:
            await interaction.followup.send(
                content=f"❌ يوجد أمر بالاسم `/{cmd_name}` مسبقاً. اختر اسماً مختلفاً.",
                ephemeral=True
            )
            return

        async with aiosqlite.connect(bot.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO custom_commands (command_name, response_text, created_by, created_at) VALUES (?, ?, ?, ?)",
                (cmd_name, response_text, interaction.user.display_name, datetime.now().isoformat())
            )
            await db.commit()

        await bot._register_single_custom_command(cmd_name, response_text)

        try:
            await bot.tree.sync()
            sync_result = "✅ تمت المزامنة"
        except Exception as e:
            sync_result = f"⚠️ فشلت المزامنة: {e}"

        await bot.log_admin_action(
            interaction.user.display_name, "اضافة_امر",
            f"إضافة أمر /{cmd_name}"
        )

        log_embed = discord.Embed(title="⚙️ إضافة أمر مخصص", color=discord.Color.blue())
        log_embed.description = (
            f"• **الأدمن:** {interaction.user.mention}\n"
            f"• **الأمر:** `/{cmd_name}`\n"
            f"• **الرد:** {response_text[:100]}{'...' if len(response_text) > 100 else ''}"
        )
        await bot.send_admin_log(log_embed)

        await interaction.followup.send(
            content=f"✅ **تم إضافة الأمر `/{cmd_name}` بنجاح!**\n{sync_result}\n\nقد يستغرق ظهوره في ديسكورد دقيقة.",
            ephemeral=True
        )


@bot.tree.command(name="اضافة_امر", description="إدارة: إضافة أمر جاهز برد مخصص")
@app_commands.checks.has_permissions(administrator=True)
async def add_custom_command(interaction: discord.Interaction):
    modal = AddCommandModal()
    await interaction.response.send_modal(modal)


@bot.tree.command(name="حذف_امر_مخصص", description="إدارة: حذف أمر مخصص")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(command_name="اسم_الأمر")
@app_commands.describe(command_name="اختر الأمر المراد حذفه")
@app_commands.autocomplete(command_name=autocomplete_custom_commands)
async def delete_custom_command(interaction: discord.Interaction, command_name: str):
    await interaction.response.defer(ephemeral=True)

    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT command_name FROM custom_commands WHERE command_name=?", (command_name,)
        ) as cursor:
            if not await cursor.fetchone():
                await interaction.followup.send(
                    content=f"❌ الأمر `/{command_name}` غير موجود في قاعدة البيانات.",
                    ephemeral=True
                )
                return

        await db.execute("DELETE FROM custom_commands WHERE command_name=?", (command_name,))
        await db.commit()

    existing_cmd = bot.tree.get_command(command_name)
    if existing_cmd:
        bot.tree.remove_command(command_name)

    try:
        await bot.tree.sync()
        sync_result = "✅ تمت المزامنة"
    except Exception as e:
        sync_result = f"⚠️ فشلت المزامنة: {e}"

    await bot.log_admin_action(
        interaction.user.display_name, "حذف_امر_مخصص",
        f"حذف أمر /{command_name}"
    )

    await interaction.followup.send(
        content=f"✅ **تم حذف الأمر `/{command_name}` بنجاح!**\n{sync_result}",
        ephemeral=True
    )


@bot.tree.command(name="قائمة_اوامر_مخصصة", description="إدارة: عرض كل الأوامر المخصصة المضافة")
@app_commands.checks.has_permissions(administrator=True)
async def list_custom_commands(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT command_name, response_text, created_by, created_at FROM custom_commands ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await interaction.followup.send(
            content="📭 لا توجد أوامر مخصصة مضافة حالياً.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"⚙️ الأوامر المخصصة ({len(rows)} أمر)",
        color=discord.Color.blue()
    )
    desc = ""
    for idx, (cmd_name, resp_text, creator, created_at) in enumerate(rows, 1):
        dt = datetime.fromisoformat(created_at).strftime('%Y/%m/%d')
        preview = resp_text[:50] + "..." if len(resp_text) > 50 else resp_text
        desc += f"**{idx}. `/{cmd_name}`**\n   📝 {preview}\n   👤 أضافه: {creator} | 📅 {dt}\n\n"

    embed.description = desc
    await interaction.followup.send(embed=embed, ephemeral=True)


# ==========================================
# معالجة أخطاء الصلاحيات
# ==========================================

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ هذا الأمر مخصص للإدارة فقط!", ephemeral=True
            )
        else:
            await interaction.followup.send("❌ هذا الأمر مخصص للإدارة فقط!", ephemeral=True)
    elif isinstance(error, app_commands.AppCommandError):
        msg = str(error)
        if not interaction.response.is_done():
            await interaction.response.send_message(msg, ephemeral=True)
        else:
            await interaction.followup.send(msg, ephemeral=True)


# ==========================================
# 📋 أوامر جديدة للأعضاء
# ==========================================

@bot.tree.command(name="الأعمال_المتاحة", description="عرض الأعمال النشطة والتخصصات المتاحة للحجز")
async def available_works(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT name, current_chapter FROM works WHERE is_active=1 ORDER BY name ASC"
            ) as cursor:
                works = await cursor.fetchall()

            if not works:
                await interaction.followup.send(content="📭 لا توجد أعمال نشطة حالياً.", ephemeral=True)
                return

            # بناء بيانات كل عمل
            works_data = []
            for w_name, w_chap in works:
                async with db.execute(
                    "SELECT role, is_booked, is_frozen FROM drive_links WHERE work_name=? AND chapter_num=?",
                    (w_name, w_chap)
                ) as cur2:
                    slots = await cur2.fetchall()

                async with db.execute(
                    "SELECT role_name FROM roles_config WHERE is_enabled=1"
                ) as cur3:
                    enabled_roles = [r[0] for r in await cur3.fetchall()]

                available_roles = []
                booked_roles = []
                completed_roles = []
                locked_roles = []  # تخصصات مفعّلة لكن ما فيها رابط

                slot_roles = {role: (is_booked, is_frozen) for role, is_booked, is_frozen in slots}

                for role in enabled_roles:
                    if role not in slot_roles:
                        locked_roles.append(role)
                    else:
                        is_booked, is_frozen = slot_roles[role]
                        if is_frozen:
                            completed_roles.append(role)
                        elif is_booked:
                            booked_roles.append(role)
                        else:
                            available_roles.append(role)

                works_data.append({
                    "name": w_name,
                    "chapter": w_chap,
                    "available": available_roles,
                    "booked": booked_roles,
                    "completed": completed_roles,
                    "locked": locked_roles
                })

        # تقسيم الأعمال إلى صفحات (5 أعمال لكل صفحة)
        page_size = 5
        pages = [works_data[i:i+page_size] for i in range(0, len(works_data), page_size)]

        def build_embed(page_idx):
            page = pages[page_idx]
            embed = discord.Embed(
                title=f"📚 الأعمال المتاحة للحجز | تيم كوكيز (صفحة {page_idx+1}/{len(pages)})",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            desc = ""
            for w in page:
                roles_text = ""
                if w["available"]:
                    roles_text += "🟢 **متاح:** " + " | ".join(w["available"]) + "\n"
                if w["booked"]:
                    roles_text += "🔴 **محجوز:** " + " | ".join(w["booked"]) + "\n"
                if w["completed"]:
                    roles_text += "✅ **مكتمل:** " + " | ".join(w["completed"]) + "\n"
                if w["locked"]:
                    roles_text += "🔒 **مقفل (لا رابط):** " + " | ".join(w["locked"]) + "\n"
                if not roles_text:
                    roles_text = "⚠️ لا توجد تخصصات مضافة بعد\n"
                desc += f"\n**{w['name']}** — الفصل `{w['chapter']}`\n{roles_text}"

            embed.description = desc[:3900]
            embed.set_footer(text="🟢 متاح  🔴 محجوز  ✅ مكتمل  🔒 مقفل | /حجز_عمل للحجز")
            return embed

        if len(pages) == 1:
            await interaction.followup.send(embed=build_embed(0), ephemeral=True)
        else:
            view = AvailableWorksPaginationView(pages, build_embed)
            await interaction.followup.send(embed=build_embed(0), view=view, ephemeral=True)
    except Exception as e:
        logger.error(f"خطأ في أمر الأعمال_المتاحة: {e}")
        await interaction.followup.send(content="❌ حدث خطأ أثناء جلب الأعمال.", ephemeral=True)


class AvailableWorksPaginationView(discord.ui.View):
    def __init__(self, pages, build_embed_func):
        super().__init__(timeout=120)
        self.pages = pages
        self.build_embed = build_embed_func
        self.current_page = 0

    @discord.ui.button(label="◀️ السابق", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(self.current_page), view=self)

    @discord.ui.button(label="▶️ التالي", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = min(len(self.pages) - 1, self.current_page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(self.current_page), view=self)

    def update_buttons(self):
        self.children[0].disabled = (self.current_page == 0)
        self.children[1].disabled = (self.current_page == len(self.pages) - 1)


@bot.tree.command(name="حجوزاتي", description="عرض حجوزاتك الحالية وحالتها")
async def my_reservations(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute("""
            SELECT r.work_name, r.chapter_num, r.role, r.time_booked,
                   COALESCE(w.max_hours, 24), r.status, r.submission_deadline
            FROM reservations r
            LEFT JOIN works w ON r.work_name = w.name
            WHERE r.user_id=?
        """, (interaction.user.id,)) as cursor:
            res_list = await cursor.fetchall()

    if not res_list:
        await interaction.followup.send(content="📭 ليس لديك حجوزات نشطة حالياً.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📋 حجوزاتك الحالية — {interaction.user.display_name}",
        color=discord.Color.teal(),
        timestamp=datetime.now()
    )
    now = datetime.now()
    desc = ""
    for idx, (work, chap, role, b_time, max_hours, status, sub_deadline) in enumerate(res_list, 1):
        booked_dt = datetime.fromisoformat(b_time)
        elapsed = now - booked_dt
        remaining_hours = max(0, max_hours - int(elapsed.total_seconds() / 3600))

        if status == 'awaiting_submission':
            status_icon = "🔄"
            status_text = "انتظار رفع الروابط"
            if sub_deadline:
                dl = datetime.fromisoformat(sub_deadline)
                mins_left = max(0, int((dl - now).total_seconds() / 60))
                status_text += f" ({mins_left} دقيقة)"
        else:
            status_icon = "⏳"
            status_text = f"قيد العمل ({remaining_hours}h متبقية)"

        desc += f"**{idx}. {work}** — فصل `{chap}` تخصص `{role}`\n   {status_icon} {status_text}\n\n"

    embed.description = desc
    embed.set_footer(text="لتسليم عمل اكتب /تم_اكتمال_عمل")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ==========================================
# 💼 أوامر إدارية جديدة
# ==========================================

@bot.tree.command(name="نقل_حجز", description="إدارة: نقل حجز من عضو إلى عضو آخر")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.rename(from_member="من_العضو", to_member="إلى_العضو", work_name="اسم_العمل", chapter_num="رقم_الفصل", role="التخصص")
@app_commands.describe(
    from_member="اختر العضو الذي يملك الحجز",
    to_member="اختر العضو الذي سينقل إليه الحجز",
    work_name="اختر اسم المانهوا",
    chapter_num="أدخل رقم الفصل",
    role="اختر التخصص"
)
@app_commands.autocomplete(work_name=autocomplete_all_works, role=autocomplete_all_roles)
async def transfer_booking(
    interaction: discord.Interaction,
    from_member: discord.Member,
    to_member: discord.Member,
    work_name: str,
    chapter_num: int,
    role: str
):
    await interaction.response.defer(ephemeral=True)

    if from_member.id == to_member.id:
        await interaction.followup.send(content="❌ العضوان متطابقان!", ephemeral=True)
        return

    async with aiosqlite.connect(bot.DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM reservations WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
            (from_member.id, work_name, chapter_num, role)
        ) as cursor:
            if not await cursor.fetchone():
                await interaction.followup.send(
                    content=f"❌ لا يوجد حجز لـ {from_member.display_name} بهذه المواصفات.",
                    ephemeral=True
                )
                return

        to_profile = await get_or_create_profile(db, to_member.id, to_member.display_name)
        if to_profile["is_excluded"] == 1:
            await interaction.followup.send(content=f"❌ {to_member.display_name} مستبعد ولا يمكن النقل إليه.", ephemeral=True)
            return

        async with db.execute(
            "SELECT COUNT(*) FROM reservations WHERE user_id=?", (to_member.id,)
        ) as cursor:
            to_slots_used = (await cursor.fetchone())[0]

        if to_slots_used >= to_profile["slots"]:
            await interaction.followup.send(
                content=f"❌ {to_member.display_name} استنفد سعة حجوزاته ({to_profile['slots']}).",
                ephemeral=True
            )
            return

        await db.execute(
            "UPDATE reservations SET user_id=?, user_name=?, time_booked=?, last_reminded=? WHERE user_id=? AND work_name=? AND chapter_num=? AND role=?",
            (to_member.id, to_member.display_name, datetime.now().isoformat(), datetime.now().isoformat(),
             from_member.id, work_name, chapter_num, role)
        )
        await db.commit()

    # إشعار العضو الجديد
    try:
        async with aiosqlite.connect(bot.DB_PATH) as db:
            async with db.execute(
                "SELECT drive_url1, drive_url2, drive_url3, drive_url4 FROM drive_links WHERE work_name=? AND chapter_num=? AND role=?",
                (work_name, chapter_num, role)
            ) as cursor:
                link_data = await cursor.fetchone()

        links_text = ""
        if link_data:
            for i, url in enumerate(link_data, 1):
                if url:
                    links_text += f"\n🔗 **رابط {i}:** {url}"

        transfer_embed = discord.Embed(title="📬 تم نقل حجز إليك", color=discord.Color.blue())
        transfer_embed.description = (
            f"تم نقل حجز إليك من قِبَل الإدارة:\n"
            f"📚 **المانهوا:** `{work_name}` فصل `{chapter_num}` تخصص `{role}`\n"
            f"📥 **روابط الدرايف:**{links_text or ' غير متاحة'}\n\n"
            f"بعد الانتهاء اكتب `/تم_اكتمال_عمل`."
        )
        await to_member.send(embed=transfer_embed)
        dm_note = "✅ تم إشعار العضو الجديد بالخاص"
    except discord.Forbidden:
        dm_note = "⚠️ فشل إرسال إشعار للعضو الجديد (الخاص مغلق)"
        fail_embed = discord.Embed(title="🚨 فشل DM عند نقل حجز", color=discord.Color.red())
        fail_embed.description = (
            f"• **العضو:** {to_member.mention}\n"
            f"• **السبب:** الخاص مغلق\n"
            f"• **الحجز:** `{work_name}` ف{chapter_num} تخصص `{role}`"
        )
        await bot.send_admin_log(fail_embed)

    await bot.log_admin_action(
        interaction.user.display_name, "نقل_حجز",
        f"من {from_member.display_name} → {to_member.display_name} | {work_name} ف{chapter_num} تخصص {role}"
    )
    log_embed = discord.Embed(title="🔄 نقل حجز", color=discord.Color.purple())
    log_embed.description = (
        f"• **الأدمن:** {interaction.user.mention}\n"
        f"• **من:** {from_member.mention}\n"
        f"• **إلى:** {to_member.mention}\n"
        f"• **الحجز:** `{work_name}` (فصل {chapter_num}) تخصص `{role}`\n"
        f"• **الإشعار:** {dm_note}"
    )
    await bot.send_admin_log(log_embed)
    await interaction.followup.send(
        content=f"✅ تم نقل الحجز من {from_member.mention} إلى {to_member.mention}.\n{dm_note}",
        ephemeral=True
    )


@bot.tree.command(name="نسخ_احتياطي_الآن", description="إدارة: إنشاء نسخة احتياطية فورية")
@app_commands.checks.has_permissions(administrator=True)
async def manual_backup_now(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await bot.auto_backup_every_3_hours()
    await bot.log_admin_action(interaction.user.display_name, "نسخ_احتياطي_الآن", "باك أب يدوي فوري")
    await interaction.followup.send(content="✅ **تم إنشاء نسخة احتياطية فورية وإرسالها لقناة الباك أب!**", ephemeral=True)


# ==========================================
# تشغيل البوت
# ==========================================
bot.run(TOKEN)