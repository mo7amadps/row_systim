import discord

def can_target(author: discord.Member, target: discord.Member) -> tuple[bool, str]:
    if author.id == target.id:
        return False, "❌ لا يمكنك تطبيق هذا الأمر على نفسك."
    
    if target.id == author.guild.owner_id:
        return False, "❌ لا يمكنك تطبيق هذا الأمر على مالك السيرفر."
        
    if author.id != author.guild.owner_id and target.top_role >= author.top_role:
        return False, "❌ لا يمكنك تطبيق هذا الأمر على شخص أعلى منك أو يساويك بالرتبة."
        
    me = author.guild.me
    if target.top_role >= me.top_role:
        return False, "❌ لا يمكن للبوت تطبيق هذا الأمر على شخص رتبته أعلى من أو تساوي رتبة البوت."
        
    return True, ""
