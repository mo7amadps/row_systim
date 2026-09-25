"""
دالة موحدة لإنشاء الـ Embeds مع إضافة فوتر "الحقوق" تلقائياً لكل embed بالبوت.
"""

import discord

CREDITS_TEXT = "discord.gg/row"


def branded_embed(**kwargs) -> discord.Embed:
    embed = discord.Embed(**kwargs)
    embed.set_footer(text=CREDITS_TEXT)
    return embed
