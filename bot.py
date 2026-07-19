import asyncio
import requests
from datetime import datetime
from telegram import Bot
import os
import logging

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(level=logging.INFO)

# ===== КОНФИГУРАЦИЯ (токены берутся из переменных окружения) =====
TELEGRAM_TOKEN = os.getenv("8935730289:AAH4GTLiauVomwDL2z3Gttv7uMP2VFV_pOc")
STRATZ_TOKEN = os.getenv("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJTdWJqZWN0IjoiZGE0OTliZWEtOWQ5Ni00ZWEwLWIzMWMtMmM3NWZhYjQ0ZTU2IiwiU3RlYW1JZCI6IjI3NTg1NTEwOCIsIkFQSVVzZXIiOiJ0cnVlIiwibmJmIjoxNzg0MTI0MTY2LCJleHAiOjE4MTU2NjAxNjYsImlhdCI6MTc4NDEyNDE2NiwiaXNzIjoiaHR0cHM6Ly9hcGkuc3RyYXR6LmNvbSJ9.dZbLNJbyieKxx18LGQnodjVIk6OjDFVQZjcJualxJVo")
CHAT_ID = os.getenv("583922132")

# ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====
tracked_matches = {}

# ===== ЗАПРОС К STRATZ API =====
def get_live_matches():
    url = "https://api.stratz.com/graphql"
    query = """
    query {
      liveMatches {
        matchId
        leagueId
        seriesId
        teamId1
        teamId2
        radiantTeamId
        direTeamId
        startedAt
      }
    }
    """
    headers = {"Authorization": f"Bearer {STRATZ_TOKEN}"}
    response = requests.post(url, headers=headers, json={"query": query})
    if response.status_code == 200:
        return response.json().get("data", {}).get("liveMatches", [])
    return []

def get_match_details(match_id):
    url = "https://api.stratz.com/graphql"
    query = """
    query GetMatch($match_id: Long!) {
      match(id: $match_id) {
        id
        didRadiantWin
        players {
          steamAccountId
          heroId
          kills
          deaths
          assists
          goldPerMinute
          xpPerMinute
          playerSlot
          lastHits
          denies
          neutralKills
          towerKills
          obsWardsPlaced
          senWardsPlaced
          wardsDestroyed
        }
      }
    }
    """
    headers = {"Authorization": f"Bearer {STRATZ_TOKEN}"}
    payload = {"query": query, "variables": {"match_id": int(match_id)}}
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json().get("data", {}).get("match")
    return None

def get_team_name(team_id):
    return f"Team_{team_id}"

def calculate_metrics(match_data):
    players = match_data["players"]
    radiant = [p for p in players if p["playerSlot"] < 5]
    dire = [p for p in players if p["playerSlot"] >= 5]

    gpm_rad = sum(p["goldPerMinute"] for p in radiant) / 5
    gpm_dir = sum(p["goldPerMinute"] for p in dire) / 5
    gold_diff = (gpm_rad - gpm_dir) / (gpm_rad + gpm_dir) * 100 if (gpm_rad + gpm_dir) > 0 else 0

    obs_rad = sum(p.get("obsWardsPlaced", 0) for p in radiant)
    obs_dir = sum(p.get("obsWardsPlaced", 0) for p in dire)
    towers_rad = sum(p.get("towerKills", 0) for p in radiant)
    towers_dir = sum(p.get("towerKills", 0) for p in dire)
    map_control = (obs_dir + towers_rad) / (obs_rad + towers_dir + 1) * 100

    best_kda = 0
    best_kda_team = "None"
    core_efficiency = 0
    for p in players:
        k = p["kills"]
        d = max(p["deaths"], 1)
        a = p["assists"]
        kda = (k + a) / d
        if kda > best_kda:
            best_kda = kda
            best_kda_team = "Radiant" if p["playerSlot"] < 5 else "Dire"
        core_efficiency = max(core_efficiency, kda * p["goldPerMinute"] / 100)

    power_spike = 15 if best_kda > 4 and max(gpm_rad, gpm_dir) > 500 else 0
    reaction_time = 0

    score = (gold_diff * 0.4) + (map_control * 0.25) + (core_efficiency * 0.2) + (power_spike * 0.1) + (reaction_time * 0.05)
    
    return {
        "score": score,
        "gold_diff": gold_diff,
        "map_control": map_control,
        "core_efficiency": core_efficiency,
        "power_spike": power_spike,
        "best_kda": best_kda,
        "best_kda_team": best_kda_team,
        "radiant_gpm": gpm_rad,
        "dire_gpm": gpm_dir
    }

async def send_notification(bot, match_id, match_data, metrics):
    team1 = get_team_name(match_data.get("radiantTeamId", "Radiant"))
    team2 = get_team_name(match_data.get("direTeamId", "Dire"))
    
    message = (
        f"🔔 **LIVE-матч Dota 2 — 15-я минута**\n"
        f"🏆 {team1} vs {team2}\n"
        f"🆔 Матч: {match_id}\n\n"
        f"📊 **Сравнительный анализ:**\n"
        f"• **Score**: {metrics['score']:.1f}\n"
        f"• **Золото**: {metrics['gold_diff']:.1f}% (Radiant: {metrics['radiant_gpm']:.0f}, Dire: {metrics['dire_gpm']:.0f})\n"
        f"• **Карта**: {metrics['map_control']:.1f}%\n"
        f"• **Эффективность кора**: {metrics['core_efficiency']:.1f}\n"
        f"• **Пауэр-спайк**: {metrics['power_spike']:.1f}\n"
        f"• **Лучший KDA**: {metrics['best_kda']:.2f} ({metrics['best_kda_team']})\n"
        f"• **Прогноз**: {'Radiant' if metrics['score'] > 0 else 'Dire'} победит с вероятностью {abs(metrics['score']):.0f}%"
    )
    
    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")

async def monitor_loop():
    bot = Bot(token=TELEGRAM_TOKEN)
    
    while True:
        try:
            logging.info(f"Проверка live-матчей...")
            live_matches = get_live_matches()
            
            for match in live_matches:
                match_id = match["matchId"]
                started_at = match.get("startedAt")
                
                if not started_at:
                    logging.warning(f"Матч {match_id} не имеет startedAt")
                    continue
                
                start_time = datetime.fromtimestamp(started_at)
                elapsed = (datetime.now() - start_time).total_seconds() / 60
                logging.info(f"Матч {match_id}: прошло {elapsed:.1f} минут")
                
                if 14 <= elapsed <= 16 and match_id not in tracked_matches:
                    tracked_matches[match_id] = {"notified": False}
                    match_data = get_match_details(match_id)
                    if match_data:
                        metrics = calculate_metrics(match_data)
                        await send_notification(bot, match_id, match, metrics)
                        tracked_matches[match_id]["notified"] = True
                        logging.info(f"Уведомление отправлено для матча {match_id}")
            
            for mid in list(tracked_matches.keys()):
                if tracked_matches[mid]["notified"]:
                    del tracked_matches[mid]
            
            await asyncio.sleep(30)
            
        except Exception as e:
            logging.error(f"Ошибка в monitor_loop: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    logging.info("🚀 Запуск бота для мониторинга live-матчей Dota 2...")
    asyncio.run(monitor_loop())
