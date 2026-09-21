"""بناء قائمة موحدة لأوامر السلاش والأوامر النصية للـ Help والـ Dashboard."""

import discord
from discord.ext import commands


def _walk_app_commands(command_list, prefix: str = "") -> list[str]:
    lines = []
    for command in sorted(command_list, key=lambda item: item.name):
        full_name = f"{prefix}{command.name}"
        description = getattr(command, "description", "") or "بدون وصف"
        lines.append(f"`/{full_name}` — {description}")
        children = getattr(command, "commands", None)
        if children:
            lines.extend(_walk_app_commands(children, f"{full_name} "))
    return lines


def command_lines(bot: commands.Bot) -> list[str]:
    """يرجع كل أوامر السلاش والأوامر النصية المسجلة فعلياً."""
    lines = ["**أوامر السلاش**"]
    lines.extend(_walk_app_commands(bot.tree.get_commands()))
    lines.append("")
    lines.append("**الأوامر النصية**")
    for command in sorted(bot.commands, key=lambda item: item.name):
        names = [command.name, *command.aliases]
        names_text = " / ".join(f"`{name}`" for name in names)
        description = command.help or command.description or "بدون وصف"
        lines.append(f"{names_text} — {description}")
    return lines


def command_embeds(
    bot: commands.Bot,
    title: str,
    color: discord.Color = discord.Color.blurple(),
) -> list[discord.Embed]:
    """يقسم قائمة الأوامر على صفحات ضمن حدود Discord."""
    lines = command_lines(bot)
    chunks = []
    current = []
    current_length = 0
    for line in lines:
        line_length = len(line) + 1
        if current and current_length + line_length > 3800:
            chunks.append(current)
            current = []
            current_length = 0
        current.append(line)
        current_length += line_length
    if current:
        chunks.append(current)

    embeds = []
    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        embed = discord.Embed(
            title=title,
            description="\n".join(chunk),
            color=color,
        )
        embed.set_footer(text=f"صفحة الأوامر {index}/{total}")
        embeds.append(embed)
    return embeds