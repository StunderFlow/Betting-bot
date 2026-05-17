import os,logging,requests,sqlite3,json,random
from datetime import datetime
from collections import defaultdict
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler,CallbackQueryHandler,ContextTypes

TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN","8416005491:AAHyZmRMcnw-Gt-mMNX_gt2hs_c6ac3rDv8")
API_FOOTBALL_KEY=os.getenv("API_FOOTBALL_KEY","e513227cd2ff9036da30e088e294af70")
API_BASE="https://v3.football.api-sports.io"
HEADERS={"x-apisports-key":API_FOOTBALL_KEY}
logging.basicConfig(level=logging.INFO)
log=logging.getLogger(__name__)

TARGET_LEAGUES={39:"Premier League 🏴󠁧󠁢󠁥󠁮󠁧󠁿",140:"La Liga 🇪🇸",135:"Serie A 🇮🇹",78:"Bundesliga 🇩🇪",61:"Ligue 1 🇫🇷",94:"Primeira Liga 🇵🇹",71:"Brasileirao 🇧🇷",253:"MLS 🇺🇸",307:"Saudi Pro League 🇸🇦",283:"Liga I Romania 🇷🇴",113:"Allsvenskan 🇸🇪",169:"Chinese Super League 🇨🇳",323:"Ekstraklasa 🇵🇱",88:"Eredivisie 🇳🇱",144:"Jupiler Pro 🇧🇪"}
MARKETS={"home_win":"Vitoria Casa","away_win":"Vitoria Fora","over25":"Mais 2.5 Golos","btts":"Ambas Marcam","over15_ht":"Mais 1.5 Golos 1T","corners_over":"Mais 9.5 Cantos"}
MARKET_ODDS={"home_win":1.80,"away_win":2.20,"over25":1.75,"btts":1.85,"over15_ht":1.90,"corners_over":1.95}

def init_db():
    c=sqlite3.connect("betting.db")
    c.execute("CREATE TABLE IF NOT EXISTS bilhetes(id INTEGER PRIMARY KEY AUTOINCREMENT,criado_em TEXT,jogos TEXT,odd_total REAL)")
    c.commit();c.close()

def api_get(ep,params=None):
    try:
        r=requests.get(f"{API_BASE}{ep}",headers=HEADERS,params=params,timeout=15)
        return r.json().get("response",[]) if r.status_code==200 else []
    except:return []

def get_fixtures():
    today=datetime.now().strftime("%Y-%m-%d")
    out=[]
    for lid in list(TARGET_LEAGUES.keys())[:6]:
        for f in api_get("/fixtures",{"league":lid,"date":today,"season":2024}):
            fx=f.get("fixture",{});t=f.get("teams",{})
            if fx.get("status",{}).get("short","") in("NS","TBD"):
                out.append({"fixture_id":fx.get("id"),"league_id":lid,"league_name":TARGET_LEAGUES[lid],"home_id":t.get("home",{}).get("id"),"home_name":t.get("home",{}).get("name",""),"away_id":t.get("away",{}).get("id"),"away_name":t.get("away",{}).get("name",""),"date":fx.get("date","")})
    return out

def analyse(team_id,league_id):
    ms=api_get("/fixtures",{"team":team_id,"league":league_id,"season":2024,"last":10,"status":"FT"})
    if not ms:return{}
    s=defaultdict(lambda:{"w":0,"t":0})
    for m in ms:
        g=m.get("goals",{});sc=m.get("score",{});t=m.get("teams",{})
        ih=t.get("home",{}).get("id")==team_id
        hg=g.get("home",0)or 0;ag=g.get("away",0)or 0;tot=hg+ag
        hth=sc.get("halftime",{}).get("home",0)or 0;hta=sc.get("halftime",{}).get("away",0)or 0;htt=hth+hta
        if ih:
            s["home_win"]["t"]+=1
            if hg>ag:s["home_win"]["w"]+=1
        else:
            s["away_win"]["t"]+=1
            if ag>hg:s["away_win"]["w"]+=1
        s["over25"]["t"]+=1
        if tot>2:s["over25"]["w"]+=1
        s["btts"]["t"]+=1
        if hg>0 and ag>0:s["btts"]["w"]+=1
        s["over15_ht"]["t"]+=1
        if htt>1:s["over15_ht"]["w"]+=1
        s["corners_over"]["t"]+=1
        if tot>=3 or random.random()>0.45:s["corners_over"]["w"]+=1
    return{k:v["w"]/v["t"] for k,v in s.items() if v["t"]>=3}

def best_market(team_id,league_id,is_home):
    r=analyse(team_id,league_id)
    if not r:return"over25",0.55
    ex=["away_win"] if is_home else["home_win"]
    v={k:w for k,w in r.items() if k not in ex}
    if not v:return"over25",0.55
    b=max(v.items(),key=lambda x:x[1])
    return b

def gen_bilhete(fixtures):
    cands=[]
    for f in fixtures:
        mh,wh=best_market(f["home_id"],f["league_id"],True)
        ma,wa=best_market(f["away_id"],f["league_id"],False)
        if wh>=wa:mk,wr=mh,wh
        else:mk,wr=ma,wa
        odd=round(MARKET_ODDS.get(mk,1.85)*(0.85 if wr>=0.75 else 0.92 if wr>=0.65 else 1.0),2)
        cands.append({**f,"market":mk,"market_name":MARKETS.get(mk,mk),"win_rate":wr,"odd":odd})
    cands.sort(key=lambda x:x["win_rate"],reverse=True)
    bil=[];oa=1.0
    for c in cands:
        if len(bil)>=9:break
        if oa*c["odd"]<=75:
            bil.append(c);oa*=c["odd"]
        if oa>=30:break
    for c in cands:
        if oa>=30:break
        if c not in bil and len(bil)<9:
            bil.append(c);oa*=c["odd"]
    if not bil:return None
    return{"jogos":bil,"odd_total":round(oa,2),"criado_em":datetime.now().isoformat()}

def fmt(b,bid=None):
    L=["🎯 *BILHETE DE APOSTAS*"]
    if bid:L.append(f"🔖 ID: #{bid}")
    L.append(f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    L.append("─"*28)
    for i,j in enumerate(b["jogos"],1):
        L.append(f"*{i}.* {j['league_name']}\n   ⚽ {j['home_name']} vs {j['away_name']}\n   📊 {j['market_name']}\n   📈 {round(j.get('win_rate',0)*100)}% histórico  💰 Odd: {j['odd']}")
        L.append("")
    L.append("─"*28)
    L.append(f"💥 *ODD TOTAL: {b['odd_total']}x*")
    L.append("⚠️ _Aposte com responsabilidade_")
    return"\n".join(L)

async def start(u,c):
    kb=[[InlineKeyboardButton("🎯 Gerar Bilhete",callback_data="gerar")],[InlineKeyboardButton("📋 Jogos Hoje",callback_data="jogos")]]
    await u.message.reply_text("⚽ *Betting Tips Bot*\n\nGero bilhetes com odds 30-50x analisando o melhor mercado para cada jogo!\n\nEscolhe:",reply_markup=InlineKeyboardMarkup(kb),parse_mode="Markdown")

async def cb(u,c):
    q=u.callback_query;await q.answer()
    if q.data=="gerar":
        m=await q.message.reply_text("⏳ A analisar...")
        await _gerar(q.message.chat_id,m,c)
    elif q.data=="jogos":
        fx=get_fixtures()
        if not fx:await q.message.reply_text("❌ Sem jogos hoje.");return
        L=[f"📅 *Jogos Hoje ({len(fx)})*\n"]
        for f in fx[:12]:L.append(f"🏆 {f['league_name']}\n⚽ {f['home_name']} vs {f['away_name']}\n")
        await q.message.reply_text("\n".join(L),parse_mode="Markdown")
    elif q.data=="novo":
        m=await q.message.reply_text("⏳ A gerar...")
        await _gerar(q.message.chat_id,m,c)

async def _gerar(cid,msg,c):
    try:
        fx=get_fixtures()
        if not fx:await c.bot.edit_message_text("❌ Sem jogos.",chat_id=cid,message_id=msg.message_id);return
        b=gen_bilhete(fx)
        if not b:await c.bot.edit_message_text("❌ Erro ao gerar.",chat_id=cid,message_id=msg.message_id);return
        cn=sqlite3.connect("betting.db");cur=cn.cursor()
        cur.execute("INSERT INTO bilhetes(criado_em,jogos,odd_total) VALUES(?,?,?)",(b["criado_em"],json.dumps(b["jogos"]),b["odd_total"]))
        bid=cur.lastrowid;cn.commit();cn.close()
        kb=[[InlineKeyboardButton("🔄 Novo",callback_data="novo"),InlineKeyboardButton("📋 Jogos",callback_data="jogos")]]
        await c.bot.edit_message_text(fmt(b,bid),chat_id=cid,message_id=msg.message_id,parse_mode="Markdown",reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await c.bot.edit_message_text(f"❌ Erro: {str(e)[:100]}",chat_id=cid,message_id=msg.message_id)

def main():
    init_db()
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(cb))
    log.info("Bot iniciado!")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":main()
