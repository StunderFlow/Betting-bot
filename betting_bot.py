import os,logging,requests,sqlite3,json,random
from datetime import datetime
from collections import defaultdict
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler,CallbackQueryHandler,ContextTypes

TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN","8810696772:AAFez5FG4fjUwWHSorY6vN_e7BfBfGAPgmI")
FD_KEY=os.getenv("FD_KEY","07620d165d3441a9af86fd54a5d6b22a")
API_BASE="https://api.football-data.org/v4"
HEADERS={"X-Auth-Token":FD_KEY}
logging.basicConfig(level=logging.INFO)
log=logging.getLogger(__name__)

COMPETITIONS={"PL":"Premier League 🏴󠁧󠁢󠁥󠁮󠁧󠁿","PD":"La Liga 🇪🇸","SA":"Serie A 🇮🇹","BL1":"Bundesliga 🇩🇪","FL1":"Ligue 1 🇫🇷","PPL":"Primeira Liga 🇵🇹","BSA":"Brasileirao 🇧🇷","CL":"Champions League 🇪🇺","DED":"Eredivisie 🇳🇱","ELC":"Championship 🏴󠁧󠁢󠁥󠁮󠁧󠁿"}
MARKETS={"home_win":"Vitoria Casa","away_win":"Vitoria Fora","over25":"Mais 2.5 Golos","btts":"Ambas Marcam","over15_ht":"Mais 1.5 Golos 1T","draw":"Empate"}
MARKET_ODDS={"home_win":1.80,"away_win":2.20,"over25":1.75,"btts":1.85,"over15_ht":1.90,"draw":3.20}

def init_db():
    c=sqlite3.connect("betting.db")
    c.execute("CREATE TABLE IF NOT EXISTS bilhetes(id INTEGER PRIMARY KEY AUTOINCREMENT,criado_em TEXT,jogos TEXT,odd_total REAL)")
    c.commit();c.close()

def api_get(ep):
    try:
        r=requests.get(f"{API_BASE}{ep}",headers=HEADERS,timeout=15)
        return r.json() if r.status_code==200 else {}
    except:return {}

def get_fixtures():
    today=datetime.now().strftime("%Y-%m-%d")
    out=[]
    for code,name in COMPETITIONS.items():
        data=api_get(f"/competitions/{code}/matches?dateFrom={today}&dateTo={today}&status=SCHEDULED")
        for m in data.get("matches",[]):
            home=m.get("homeTeam",{})
            away=m.get("awayTeam",{})
            out.append({
                "fixture_id":m.get("id"),
                "competition":code,
                "league_name":name,
                "home_id":home.get("id"),
                "home_name":home.get("name",""),
                "away_id":away.get("id"),
                "away_name":away.get("name",""),
                "date":m.get("utcDate","")
            })
    return out

def analyse(team_id,competition):
    data=api_get(f"/teams/{team_id}/matches?competitions={competition}&status=FINISHED&limit=10")
    ms=data.get("matches",[])
    if not ms:return{}
    s=defaultdict(lambda:{"w":0,"t":0})
    for m in ms:
        home=m.get("homeTeam",{})
        away=m.get("awayTeam",{})
        score=m.get("score",{}).get("fullTime",{})
        ht=m.get("score",{}).get("halfTime",{})
        ih=home.get("id")==team_id
        hg=score.get("home",0)or 0
        ag=score.get("away",0)or 0
        tot=hg+ag
        hth=ht.get("home",0)or 0
        hta=ht.get("away",0)or 0
        htt=hth+hta
        if ih:
            s["home_win"]["t"]+=1
            if hg>ag:s["home_win"]["w"]+=1
        else:
            s["away_win"]["t"]+=1
            if ag>hg:s["away_win"]["w"]+=1
        s["draw"]["t"]+=1
        if hg==ag:s["draw"]["w"]+=1
        s["over25"]["t"]+=1
        if tot>2:s["over25"]["w"]+=1
        s["btts"]["t"]+=1
        if hg>0 and ag>0:s["btts"]["w"]+=1
        s["over15_ht"]["t"]+=1
        if htt>1:s["over15_ht"]["w"]+=1
    return{k:v["w"]/v["t"] for k,v in s.items() if v["t"]>=3}

def best_market(team_id,competition,is_home):
    r=analyse(team_id,competition)
    if not r:return"over25",0.55
    ex=["away_win"] if is_home else["home_win"]
    v={k:w for k,w in r.items() if k not in ex}
    if not v:return"over25",0.55
    b=max(v.items(),key=lambda x:x[1])
    return b

def gen_bilhete(fixtures):
    cands=[]
    for f in fixtures:
        mh,wh=best_market(f["home_id"],f["competition"],True)
        ma,wa=best_market(f["away_id"],f["competition"],False)
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
    L=["\u26bd *BILHETE DE APOSTAS*"]
    if bid:L.append(f"\U0001f516 ID: #{bid}")
    L.append(f"\U0001f4c5 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    L.append("\u2500"*28)
    for i,j in enumerate(b["jogos"],1):
        hora=""
        if j.get("date"):
            try:
                dt=datetime.fromisoformat(j["date"].replace("Z","+00:00"))
                hora=dt.strftime("%H:%M")
            except:pass
        L.append(f"*{i}.* {j['league_name']}\n   \u26bd {j['home_name']} vs {j['away_name']}\n   \U0001f4ca {j['market_name']} | {round(j.get('win_rate',0)*100)}% hist.\n   \U0001f4b0 Odd: `{j['odd']}`" + (f" \U0001f550 {hora}" if hora else ""))
        L.append("")
    L.append("\u2500"*28)
    L.append(f"\U0001f4a5 *ODD TOTAL: {b['odd_total']}x*")
    L.append("\u26a0\ufe0f _Aposte com responsabilidade_")
    return"\n".join(L)

async def start(u,c):
    kb=[[InlineKeyboardButton("\U0001f3af Gerar Bilhete",callback_data="gerar")],[InlineKeyboardButton("\U0001f4cb Jogos Hoje",callback_data="jogos")],[InlineKeyboardButton("\U0001f4dc Historico",callback_data="historico")]]
    await u.message.reply_text("\u26bd *Betting Tips Bot*\n\nAnaliso estatisticas de 10 ligas e gero bilhetes com odds 30-50x!\n\nEscolhe:",reply_markup=InlineKeyboardMarkup(kb),parse_mode="Markdown")

async def cb(u,c):
    q=u.callback_query;await q.answer()
    if q.data=="gerar":
        m=await q.message.reply_text("\u23f3 A analisar jogos...")
        await _gerar(q.message.chat_id,m,c)
    elif q.data=="jogos":
        await q.message.reply_text("\u23f3 A buscar jogos...")
        fx=get_fixtures()
        if not fx:await q.message.reply_text("\u274c Sem jogos hoje.");return
        L=[f"\U0001f4c5 *Jogos Hoje ({len(fx)})*\n"]
        for f in fx[:15]:L.append(f"\U0001f3c6 {f['league_name']}\n\u26bd {f['home_name']} vs {f['away_name']}\n")
        await q.message.reply_text("\n".join(L),parse_mode="Markdown")
    elif q.data=="historico":
        cn=sqlite3.connect("betting.db");cur=cn.cursor()
        rows=cur.execute("SELECT id,criado_em,odd_total FROM bilhetes ORDER BY id DESC LIMIT 5").fetchall();cn.close()
        if not rows:await q.message.reply_text("\U0001f4ed Sem bilhetes ainda.");return
        L=["\U0001f4dc *Ultimos Bilhetes*\n"]
        for r in rows:L.append(f"\U0001f516 #{r[0]} | {r[1][:16].replace('T',' ')} | Odd: {r[2]}x")
        await q.message.reply_text("\n".join(L),parse_mode="Markdown")
    elif q.data in("novo","gerar"):
        m=await q.message.reply_text("\u23f3 A gerar...")
        await _gerar(q.message.chat_id,m,c)

async def _gerar(cid,msg,c):
    try:
        fx=get_fixtures()
        if not fx:await c.bot.edit_message_text("\u274c Sem jogos hoje.",chat_id=cid,message_id=msg.message_id);return
        b=gen_bilhete(fx)
        if not b:await c.bot.edit_message_text("\u274c Nao foi possivel gerar bilhete.",chat_id=cid,message_id=msg.message_id);return
        cn=sqlite3.connect("betting.db");cur=cn.cursor()
        cur.execute("INSERT INTO bilhetes(criado_em,jogos,odd_total) VALUES(?,?,?)",(b["criado_em"],json.dumps(b["jogos"]),b["odd_total"]))
        bid=cur.lastrowid;cn.commit();cn.close()
        kb=[[InlineKeyboardButton("\U0001f504 Novo Bilhete",callback_data="gerar"),InlineKeyboardButton("\U0001f4cb Jogos",callback_data="jogos")]]
        await c.bot.edit_message_text(fmt(b,bid),chat_id=cid,message_id=msg.message_id,parse_mode="Markdown",reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await c.bot.edit_message_text(f"\u274c Erro: {str(e)[:100]}",chat_id=cid,message_id=msg.message_id)

def main():
    init_db()
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(cb))
    log.info("Bot iniciado!")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":main()
