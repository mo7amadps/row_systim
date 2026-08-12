import discord
from discord.ext import commands
from discord import app_commands
from utils.checks import can_target
from utils.embeds import branded_embed

class FastRoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="help", description="عرض قائمة الأوامر والمساعدة")
    async def help_command(self, ctx: commands.Context):
        """أمر المساعدة الرئيسي المترابط ودعم السلاش والمباشر"""
        embed = branded_embed(
            title="📜 قائمة الأوامر والمساعدة",
            description="جميع أوامر البوت تعمل الآن بالنظامين النصي (`!`) والسلاش (`/`).",
            color=discord.Color.blue()
        )
        embed.add_field(name="⚡ /مفصول [عضو] [سبب]", value="سحب جميع الرتب الثانوية فوراً من العضو.", inline=False)
        embed.add_field(name="❓ /help", value="عرض هذه القائمة من المساعدة.", inline=False)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="مفصول", description="سحب الرتب غير الأساسية من العضو فوراً بدون إزعاج الرتب")
    @app_commands.describe(member="العضو المراد سحب رتبه", reason="سبب سحب الرتب")
    @commands.has_permissions(manage_roles=True)
    async def fast_unrole(self, ctx: commands.Context, member: discord.Member, reason: str = "سحب الرتب بأمر مفصول السريع"):
        ok, msg = can_target(ctx.author, member)
        if not ok:
            return await ctx.send(msg, ephemeral=True if ctx.interaction else False)

        bot_top_role = ctx.guild.me.top_role
        roles_to_remove = [
            role for role in member.roles 
            if not role.is_default() and role < bot_top_role and not role.managed
        ]

        if not roles_to_remove:
            return await ctx.send("⚠️ العضو لا يملك رتب قابلة للإزالة أو رتبته أعلى من البوت.", ephemeral=True if ctx.interaction else False)

        try:
            # Defer interaction to avoid "Application did not respond"
            if ctx.interaction:
                await ctx.interaction.response.defer()

            await member.remove_roles(*roles_to_remove, reason=f"بواسطة {ctx.author} | السبب: {reason}")
            
            embed = branded_embed(
                title="⚡ تم سحب الرتب بنجاح (مفصول)",
                description=f"تم إزالة **{len(roles_to_remove)}** رتبة من العضو {member.mention}.",
                color=discord.Color.orange()
            )
            embed.add_field(name="المنفذ", value=ctx.author.mention, inline=True)
            embed.add_field(name="السبب", value=reason, inline=True)
            
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ البوت لا يمتلك الصلاحيات الكافية لتعديل رتب هذا الشخص.")
        except Exception as e:
            await ctx.send(f"❌ حدث خطأ أثناء سحب الرتب: {e}")

async def setup(bot):
    await bot.add_cog(FastRoleManagement(bot))
