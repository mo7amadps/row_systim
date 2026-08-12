import discord

CREDITS_TEXT = "discord.gg/row"

def branded_embed(**kwargs) -> discord.Embed:
    embed = discord.Embed(**kwargs)
    embed.set_footer(text=CREDITS_TEXT)
    return embed

def safe_add_field(embed: discord.Embed, name: str, value: str, inline: bool = False):
    str_value = str(value) if value is not None else "لا يوجد"
    if len(str_value) > 1000:
        str_value = str_value[:990] + "\n...(تم اقتطاع النص للتجاوز)"
    embed.add_field(name=name, value=str_value, inline=inline)
