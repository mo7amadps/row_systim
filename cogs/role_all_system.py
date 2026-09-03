import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import bot_missing_permissions, is_dangerous_role
from utils.embeds import branded_embed

TARGET_LABELS = {
    "all": "👥 الكل",
    "members": "🙋 الأعضاء بس",
    "bots": "🤖 البوتات بس",
}


class TargetSelect(discord.ui.Select):
    def __init__(self, flow: "RoleAllFlow"):
        options = [
            discord.SelectOption(label="الكل", description="كل أعضاء السيرفر (أعضاء + بوتات)", value="all", emoji="👥"),
            discord.SelectOption(label="الأعضاء بس", description="بدون البوتات", value="members", emoji="🙋"),
            discord.SelectOption(label="البوتات بس", description="بدون الأعضاء", value="bots", emoji="🤖"),
        ]
        super().__init__(placeholder="مين بدك تعطيه الرتبة؟", options=options, min_values=1, max_values=1)
        self.flow = flow

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        self.flow.target_mode = self.values[0]
        await self.flow.show_role_select(interaction)


class TargetView(discord.ui.View):
    def __init__(self, flow: "RoleAllFlow"):
        super().__init__(timeout=120)
        self.flow = flow
        self.add_item(TargetSelect(flow))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        try:
            await self.flow.disable_and_timeout()
        except Exception:
            pass


class RolePickSelect(discord.ui.RoleSelect):
    def __init__(self, flow: "RoleAllFlow"):
        super().__init__(placeholder="اختر الرتبة يلي بدك تعطيها", min_values=1, max_values=1)
        self.flow = flow

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        role = self.values[0]
        ok, err = self.flow.validate_role(role)
        if not ok:
            await interaction.response.send_message(f"❌ {err}", ephemeral=True)
            return
        self.flow.role = role
        await self.flow.show_confirm(interaction)


class RolePickView(discord.ui.View):
    def __init__(self, flow: "RoleAllFlow"):
        super().__init__(timeout=120)
        self.flow = flow
        self.add_item(RolePickSelect(flow))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        try:
            await self.flow.disable_and_timeout()
        except Exception:
            pass


class ConfirmView(discord.ui.View):
    def __init__(self, flow: "RoleAllFlow"):
        super().__init__(timeout=60)
        self.flow = flow

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="متأكد ✅", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        await self.flow.execute(interaction)

    @discord.ui.button(label="إلغاء ❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.flow.invoker.id:
            await interaction.response.send_message("هاد الأمر مو إلك.", ephemeral=True)
            return
        await interaction.response.edit_message(content="❌ تم الإلغاء.", embed=None, view=None)


class RoleAllFlow:
    def __init__(self, cog: "RoleAllSystem", interaction: discord.Interaction):
        self.cog = cog
        self.invoker = interaction.user
        self.guild = interaction.guild
        self.target_mode = None
        self.role: discord.Role = None

    async def start(self, interaction: discord.Interaction):
        embed = branded_embed(
            title="👥 إعطاء رتبة للكل",
            description="اختر الفئة المستهدفة 👇",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=TargetView(self))

    async def disable_and_timeout(self):
        pass  # الرسالة الأصلية بتنتهي مهلتها تلقائياً من ديسكورد نفسه

    def validate_role(self, role: discord.Role):
        if role.is_default():
            return False, "ما فيك تختار @everyone."
        if role.managed:
            return False, "هاي رتبة تلقائية تابعة لبوت، ما فيك تتحكم فيها."
        if is_dangerous_role(role):
            return False, "هاي رتبة فيها صلاحيات حساسة (إدارية)، ما فيك تستخدمها بهاد الأمر."
        is_owner = self.invoker.id == self.guild.owner_id
        if not is_owner and role.position >= self.invoker.top_role.position:
            return False, "ما فيك تتحكم بهاي الرتبة، هي أعلى من رتبتك أو تساويها."
        if role.position >= self.guild.me.top_role.position:
            return False, "رتبة البوت لازم تكون أعلى من هاي الرتبة حتى يقدر يتحكم فيها."
        return True, ""

    def target_members(self):
        if self.target_mode == "all":
            return list(self.guild.members)
        if self.target_mode == "members":
            return [m for m in self.guild.members if not m.bot]
        return [m for m in self.guild.members if m.bot]

    async def show_role_select(self, interaction: discord.Interaction):
        label = TARGET_LABELS[self.target_mode]
        embed = branded_embed(
            title="👥 إعطاء رتبة للكل",
            description=f"الفئة: {label}\nاختر الرتبة يلي بدك تعطيها 👇",
            color=discord.Color.blurple(),
        )
        await interaction.response.edit_message(embed=embed, view=RolePickView(self))

    async def show_confirm(self, interaction: discord.Interaction):
        label = TARGET_LABELS[self.target_mode]
        count = len(self.target_members())
        embed = branded_embed(title="⚠️ هل أنت متأكد؟", color=discord.Color.orange())
        embed.add_field(name="الفئة", value=label, inline=True)
        embed.add_field(name="عدد الأشخاص", value=str(count), inline=True)
        embed.add_field(name="الرتبة", value=self.role.mention, inline=False)
        await interaction.response.edit_message(embed=embed, view=ConfirmView(self))

    async def execute(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content="⏳ عم أعطي الرتبة... ممكن ياخد شوي وقت حسب عدد الأشخاص.",
            embed=None, view=None,
        )

        guild = self.guild
        fresh_invoker = guild.get_member(self.invoker.id)
        if fresh_invoker is None:
            await interaction.edit_original_response(content="❌ ما عاد لاقيك بالسيرفر.")
            return

        ok, err = self.validate_role(self.role)
        if not ok:
            await interaction.edit_original_response(content=f"❌ {err}")
            return

        missing = bot_missing_permissions(guild, "manage_roles")
        if missing:
            await interaction.edit_original_response(content=f"❌ البوت ما معه صلاحية كافية: {', '.join(missing)}")
            return

        bot_top_position = guild.me.top_role.position
        members = self.target_members()
        added = 0
        skipped = 0
        for member in members:
            if self.role in member.roles:
                skipped += 1
                continue
            if member.top_role.position >= bot_top_position and member.id != guild.owner_id:
                skipped += 1
                continue
            try:
                await member.add_roles(self.role, reason=f"role-all بواسطة {self.invoker}")
                added += 1
            except discord.HTTPException:
                skipped += 1
            await asyncio.sleep(0.3)

        await interaction.edit_original_response(
            content=f"✅ خلصت! تمت إضافة رتبة {self.role.mention} لـ **{added}** شخص. (اتخطى {skipped})"
        )

        await self.cog.send_log(guild, {
            "العملية": "👥 role-all",
            "بواسطة": self.invoker.mention,
            "الفئة": TARGET_LABELS[self.target_mode],
            "الرتبة": self.role.mention,
            "تمت الإضافة": added,
            "تم التخطي": skipped,
        })


class RoleAllSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_log(self, guild: discord.Guild, fields: dict):
        from utils.storage import Storage
        conf = await Storage.get_guild(guild.id)
        channel_id = conf["role_assign"].get("log_channel_id")
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return
        embed = branded_embed(title="📋 سجل رول", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=False)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

    @app_commands.command(name="role-all", description="إعطاء رتبة للكل / الأعضاء بس / البوتات بس")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def role_all_cmd(self, interaction: discord.Interaction):
        flow = RoleAllFlow(self, interaction)
        await flow.start(interaction)

    @role_all_cmd.error
    async def role_all_cmd_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ لازم تكون أدمن حتى تستخدم هاد الأمر.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RoleAllSystem(bot))
