import discord
from discord.ext import commands
from utils.checks import can_target
from utils.embeds import branded_embed

class FastRoleManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="مفصول", aliases=["unrole", "removeroles"])
    @commands.has_permissions(manage_roles=True)
    async def fast_unrole(self, ctx, member: discord.Member, *, reason: str = "سحب الرتب بأمر مفصول السريع"):
        """أمر سريع لسحب الرتب غير الأساسية من العضو مباشرة بدون منشن للرتب"""
        ok, msg = can_target(ctx.author, member)
        if not ok:
            return await ctx.reply(msg)

        bot_top_role = ctx.guild.me.top_role
        roles_to_remove = [
            role for role in member.roles 
            if not role.is_default() and role < bot_top_role and not role.managed
        ]

        if not roles_to_remove:
            return await ctx.reply("⚠️ العضو لا يملك رتب قابلة للإزالة أو رتبته أعلى من البوت.")

        try:
            await member.remove_roles(*roles_to_remove, reason=f"بواسطة {ctx.author} | السبب: {reason}")
            
            embed = branded_embed(
                title="⚡ تم سحب الرتب بنجاح (مفصول)",
                description=f"تم إزالة **{len(roles_to_remove)}** رتبة من العضو {member.mention}.",
                color=discord.Color.orange()
            )
            embed.add_field(name="المنفذ", value=ctx.author.mention, inline=True)
            embed.add_field(name="السبب", value=reason, inline=True)
            
            await ctx.reply(embed=embed)
        except discord.Forbidden:
            await ctx.reply("❌ البوت لا يمتلك الصلاحيات الكافية لتعديل رتب هذا الشخص.")
        except Exception as e:
            await ctx.reply(f"❌ حدث خطأ أثناء سحب الرتب: {e}")

async def setup(bot):
    await bot.add_cog(FastRoleManagement(bot))
