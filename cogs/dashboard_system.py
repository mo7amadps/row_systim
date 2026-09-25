import discord
from discord import app_commands
from discord.ext import commands

from utils.storage import Storage
from utils.embeds import branded_embed
from utils.command_catalog import command_embeds


def _roles_txt(guild: discord.Guild, role_ids: list) -> str:
    if not role_ids:
        return "—"
    return ", ".join(f"<@&{i}>" for i in role_ids)


def _channel_txt(guild: discord.Guild, channel_id) -> str:
    return f"<#{channel_id}>" if channel_id else "—"


def _configured_mark(is_configured: bool) -> str:
    return "✅" if is_configured else "❌"


class DashboardSystem(commands.Cog):
    """أمر واحد يلخص كل إعدادات البوت بالسيرفر (متل داشبورد مصغّر) - بصفحات."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _page_moderation(self, guild: discord.Guild, conf: dict) -> discord.Embed:
        embed = branded_embed(title="⚙️ الداشبورد - الإشراف الأساسي", color=discord.Color.blurple())

        t = conf["time"]
        embed.add_field(
            name=f"{_configured_mark(bool(t['giver_role_ids']))} تايم",
            value=f"الرتب: {_roles_txt(guild, t['giver_role_ids'])}\nالحد اليومي: {t['daily_limit'] or '—'}\nاللوق: {_channel_txt(guild, t['log_channel_id'])}",
            inline=True,
        )
        w = conf["warn"]
        embed.add_field(
            name=f"{_configured_mark(bool(w['allowed_role_ids']))} تحذير",
            value=f"الرتب: {_roles_txt(guild, w['allowed_role_ids'])}\nاللوق: {_channel_txt(guild, w['log_channel_id'])}",
            inline=True,
        )
        b = conf["ban"]
        embed.add_field(
            name=f"{_configured_mark(bool(b['allowed_role_ids']))} باند",
            value=f"الرتب: {_roles_txt(guild, b['allowed_role_ids'])}\nالحد اليومي: {b['daily_limit'] or '—'}\nاللوق: {_channel_txt(guild, b['log_channel_id'])}",
            inline=True,
        )
        nk = conf["nickname"]
        embed.add_field(
            name=f"{_configured_mark(bool(nk['allowed_role_ids']))} نك",
            value=f"الرتب: {_roles_txt(guild, nk['allowed_role_ids'])}",
            inline=True,
        )
        rar = conf["rar"]
        embed.add_field(
            name=f"{_configured_mark(bool(rar['allowed_role_ids']))} rar",
            value=f"الرتب: {_roles_txt(guild, rar['allowed_role_ids'])}",
            inline=True,
        )
        cl = conf["clear"]
        embed.add_field(
            name=f"{_configured_mark(bool(cl['allowed_role_ids']))} مسح",
            value=f"الرتب: {_roles_txt(guild, cl['allowed_role_ids'])}",
            inline=True,
        )
        clv2 = conf["clear_v2"]
        embed.add_field(
            name=f"{_configured_mark(bool(clv2['allowed_role_ids']) and bool(clv2['protected_role_id']))} مسح شخص محدد",
            value=(
                f"الرتب: {_roles_txt(guild, clv2['allowed_role_ids'])}\n"
                f"أقصى عدد: {clv2.get('max_amount', 50)}\n"
                f"الرتبة المحمية: {_roles_txt(guild, [clv2['protected_role_id']] if clv2['protected_role_id'] else [])}"
            ),
            inline=True,
        )
        lock = conf["lock"]
        unlock = conf["unlock"]
        embed.add_field(
            name=f"{_configured_mark(bool(lock['allowed_role_ids']) or bool(unlock['allowed_role_ids']))} قفل/فتح القنوات",
            value=f"قفل: {_roles_txt(guild, lock['allowed_role_ids'])}\nفتح: {_roles_txt(guild, unlock['allowed_role_ids'])}",
            inline=True,
        )
        prison = conf["prison"]
        embed.add_field(
            name=f"{_configured_mark(bool(prison['imprison_role_ids']))} السجن",
            value=f"مسجونين حالياً: {len(prison.get('jailed', {}))}\nروم السجن: {_channel_txt(guild, prison['prison_channel_id'])}",
            inline=True,
        )
        embed.set_footer(text=f"{embed.footer.text} • الإشراف الأساسي")
        return embed

    def _page_roles(self, guild: discord.Guild, conf: dict) -> discord.Embed:
        embed = branded_embed(title="⚙️ الداشبورد - الرتب والترقيات", color=discord.Color.blurple())

        role_cfg = conf["role"]
        embed.add_field(
            name=f"{_configured_mark(bool(role_cfg['allowed_role_ids']))} رول",
            value=f"الرتب: {_roles_txt(guild, role_cfg['allowed_role_ids'])}",
            inline=True,
        )
        add_r = conf["add_role"]
        embed.add_field(
            name=f"{_configured_mark(bool(add_r['allowed_role_ids']))} ترقية",
            value=f"الرتب: {_roles_txt(guild, add_r['allowed_role_ids'])}",
            inline=True,
        )
        rm_r = conf["remove_role"]
        embed.add_field(
            name=f"{_configured_mark(bool(rm_r['allowed_role_ids']))} تخفيض",
            value=f"الرتب: {_roles_txt(guild, rm_r['allowed_role_ids'])}",
            inline=True,
        )
        for key, label in (("staff", "صغرى"), ("highstaff", "عليا"), ("owner", "اونر")):
            c = conf[key]
            embed.add_field(
                name=f"{_configured_mark(bool(c['allowed_role_ids']))} {label} (نظام رتب)",
                value=(
                    f"من: {_roles_txt(guild, [c['first_role_id']] if c['first_role_id'] else [])}\n"
                    f"إلى: {_roles_txt(guild, [c['last_role_id']] if c['last_role_id'] else [])}"
                ),
                inline=True,
            )
        dismiss = conf["dismiss"]
        embed.add_field(
            name=f"{_configured_mark(bool(dismiss['allowed_role_ids']))} مفصول",
            value=f"الرتب: {_roles_txt(guild, dismiss['allowed_role_ids'])}",
            inline=True,
        )
        embed.set_footer(text=f"{embed.footer.text} • الرتب والترقيات")
        return embed

    def _page_security(self, guild: discord.Guild, conf: dict) -> discord.Embed:
        embed = branded_embed(title="⚙️ الداشبورد - نظام الحماية", color=discord.Color.blurple())
        sec = conf["security"]
        labels = {
            "bot_add": "إضافة بوتات",
            "prune": "حذف جماعي",
            "webhook": "الويبهوكس",
            "channels": "الرومات",
            "roles": "الرتب",
            "permission_escalation": "تصعيد الصلاحيات",
            "guild_update": "إعدادات السيرفر",
            "rate_limit": "حد الإجراءات الخطيرة",
        }
        for key, label in labels.items():
            c = sec.get(key, {})
            embed.add_field(
                name=f"{_configured_mark(bool(c.get('allowed_role_ids')))} حماية {label}",
                value=f"اللوق: {_channel_txt(guild, c.get('log_channel_id'))}\nرتبة الإشعار: {_roles_txt(guild, [c['notify_role_id']] if c.get('notify_role_id') else [])}",
                inline=True,
            )
        embed.set_footer(text=f"{embed.footer.text} • الحماية")
        return embed

    def _page_xp(self, guild: discord.Guild, conf: dict) -> discord.Embed:
        embed = branded_embed(title="⚙️ الداشبورد - نظام XP", color=discord.Color.blurple())
        xp = conf["xp"]
        voice = conf["voice_xp"]

        embed.add_field(
            name="✅ الكتابة",
            value=f"XP بالرسالة: {xp['xp_min']}-{xp['xp_max']}\nالكولداون: {xp['cooldown_seconds']} ثانية\nعدد المتفاعلين: {len(xp.get('users', {}))}",
            inline=True,
        )
        embed.add_field(
            name="✅ الفويس" if voice["xp_per_minute"] > 0 else "❌ الفويس (معطّل)",
            value=f"XP بالدقيقة: {voice['xp_per_minute']}\nعدد المتفاعلين: {len(voice.get('users', {}))}",
            inline=True,
        )
        embed.add_field(
            name="ℹ️ إعدادات إضافية",
            value=(
                f"روم اللفل أب: {_channel_txt(guild, xp['levelup_channel_id']) if xp['levelup_channel_id'] else 'نفس روم الرسالة'}\n"
                f"قناة اللوق: {_channel_txt(guild, xp['log_channel_id'])}\n"
                f"رومات مستثناة: {len(xp.get('no_xp_channel_ids', []))}\n"
                f"رتب مستثناة: {len(xp.get('no_xp_role_ids', []))}\n"
                f"رتب مكافآت مستوى: {len(xp.get('role_rewards', {}))}"
            ),
            inline=False,
        )
        embed.set_footer(text=f"{embed.footer.text} • XP")
        return embed

    def _page_quests(self, guild: discord.Guild, conf: dict) -> discord.Embed:
        embed = branded_embed(title="⚙️ الداشبورد - نظام المهام", color=discord.Color.blurple())
        for key, label in (("quest_staff", "صغرى"), ("quest_highstaff", "عليا"), ("quest_owner", "اونر")):
            c = conf[key]
            configured = bool(
                c["allowed_role_ids"] and c["first_role_id"] and c["last_role_id"]
                and c["log_channel_id"] and c["quest_channel_id"] and c["target_role_id"]
            )
            embed.add_field(
                name=f"{_configured_mark(configured)} مهام {label}",
                value=(
                    f"الرتب المسموحة: {_roles_txt(guild, c['allowed_role_ids'])}\n"
                    f"من: {_roles_txt(guild, [c['first_role_id']] if c['first_role_id'] else [])} "
                    f"إلى: {_roles_txt(guild, [c['last_role_id']] if c['last_role_id'] else [])}\n"
                    f"روم النشر: {_channel_txt(guild, c['quest_channel_id'])}\n"
                    f"موجهة لرتبة: {_roles_txt(guild, [c['target_role_id']] if c['target_role_id'] else [])}\n"
                    f"اللوق: {_channel_txt(guild, c['log_channel_id'])}"
                ),
                inline=False,
            )
        active = conf["quests"]["active"]
        if active:
            lines = []
            for tier, quest in active.items():
                if quest:
                    tier_label = {"staff": "صغرى", "highstaff": "عليا", "owner": "اونر"}[tier]
                    status = "🟢 شغالة" if quest.get("status") == "live" else "🗓️ مجدولة"
                    lines.append(f"**{tier_label}**: {status} - هدف {quest.get('goal')} XP")
            if lines:
                embed.add_field(name="📌 مهمات فعّالة حالياً", value="\n".join(lines), inline=False)
        embed.set_footer(text=f"{embed.footer.text} • المهام")
        return embed

    def _page_logs(self, guild: discord.Guild, conf: dict) -> discord.Embed:
        embed = branded_embed(title="⚙️ الداشبورد - قنوات اللوق (mo7-log)", color=discord.Color.blurple())
        rows = [
            ("🔨 باند", conf["ban"].get("log_channel_id")),
            ("⚠️ تحذير", conf["warn"].get("log_channel_id")),
            ("⏱️ تايم", conf["time"].get("log_channel_id")),
            ("🔓 فك باند", conf["unban"].get("log_channel_id")),
            ("🧹 مسح", conf["clear"].get("log_channel_id")),
            ("💬 رسائل (حذف/تعديل)", conf["message_log"].get("channel_id")),
            ("📥 دخول", conf["join_log"].get("channel_id")),
            ("📤 خروج", conf["leave_log"].get("channel_id")),
            ("🔗 ويب هوك", conf["security"]["webhook"].get("log_channel_id")),
            ("🤖 كل الأوامر", conf["command_log"].get("channel_id")),
        ]
        for label, channel_id in rows:
            embed.add_field(name=label, value=_channel_txt(guild, channel_id), inline=True)
        embed.add_field(
            name="🛡️ حماية عام (7 أنظمة)",
            value=", ".join(
                _channel_txt(guild, conf["security"][sub].get("log_channel_id"))
                for sub in ("bot_add", "prune", "channels", "roles", "permission_escalation", "guild_update", "rate_limit")
            ),
            inline=False,
        )
        embed.set_footer(text=f"{embed.footer.text} • اللوقات • عدّلها بـ /mo7-log")
        return embed

    async def _build_pages(self, guild: discord.Guild) -> list:
        conf = await Storage.get_guild(guild.id)
        pages = [
            self._page_moderation(guild, conf),
            self._page_roles(guild, conf),
            self._page_security(guild, conf),
            self._page_xp(guild, conf),
            self._page_quests(guild, conf),
            self._page_logs(guild, conf),
        ]
        pages.extend(
            command_embeds(
                self.bot,
                "📚 كل أوامر البوت",
                discord.Color.dark_teal(),
            )
        )
        return pages

    @commands.command(name="اعدادات", aliases=["داشبورد"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def dashboard_cmd(self, ctx: commands.Context):
        pages = await self._build_pages(ctx.guild)
        view = DashboardView(pages, ctx.author.id)
        await ctx.reply(embed=pages[0], view=view)

    @dashboard_cmd.error
    async def dashboard_cmd_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            return

    @app_commands.command(name="dashboard", description="عرض ملخص كل إعدادات البوت بالسيرفر")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard_slash(self, interaction: discord.Interaction):
        pages = await self._build_pages(interaction.guild)
        view = DashboardView(pages, interaction.user.id)
        await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)

    @dashboard_slash.error
    async def dashboard_slash_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            return


class DashboardView(discord.ui.View):
    def __init__(self, pages: list, author_id: int):
        super().__init__(timeout=120)
        self.pages = pages
        self.author_id = author_id
        self.page = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ بس يلي طلب الداشبورد فيه يتصفح الصفحات.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(len(self.pages) - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(DashboardSystem(bot))
