import os,logging,requests,sqlite3,json,random
from datetime import datetime,time
from collections import defaultdict
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler,CallbackQueryHandler,ContextTypes,JobQueue
import asyncio

TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN","8810696772:AAFez5FG4fjUwWHSorY6vN_e7BfBfGAPgmI")
FD_KEY=os.getenv("FD_KEY","07620d165d3441a9af86fd54a5d6b22a")
API_BASE="https://api.football-data.org/v4"
HEADERS={"X-Auth-Token":FD_KEY}
logging.basicConfig(level=logging.INFO)
log=logging.getLogger(__name__)

COMPETITIONS={"PL":"Premier League 🏴󠁧󠁢󠁥󠁮󠁧󠁿","PD":"La Liga 🇪🇸","SA":"Serie A 🇮🇹","BL1":"Bundesliga 🇩🇪","FL1":"Ligue 1 🇫🇷","PPL":"Primeira Liga 🇵🇹","BSA":"Brasileirao 🇧🇷","CL":"Champions League 🇪🇺","DED":"Eredivisie 🇳🇱","ELC":"Championship 🏴󠁧󠁢󠁥󠁮󠁧󠁿"}
MARKETS={"home_win":"Vitoria Casa","away_win":"Vitoria Fora","over25":"Mais 2.5 Golos","btts":"Ambas Marcam","over15_ht":"Mais 1.5 Golos 1T","draw":"Empate","over05_ht":"Mais 0.5 Golos 1T"}
MARKET_ODDS={"home_win":1.80,"away_win":2.20,"over25":1.75,"btts":1.85,"over15_ht":1.90,"draw":3.20,"over05_ht":1.40}
CONFIANCA={0.75:"🔥 Alta","default":"⚡ Media",0.55:"💧 Baixa"}

CHAT_IDS=set()

def init_db():
    c=sqlite3.connect("betting.db")
    c.execute("CREATE TABLE IF NOT EXISTS bilhetes(id INTEGER PRIMARY KEY AUTOINCREMENT,criado_em TEXT,jogos TEXT,odd_total REAL,tipo TEXT DEFAULT 'simples')")
    c.execute("CREATE TABLE IF NOT EXISTS chats(chat_id INTEGER PRIMARY KEY)")
    for row in c.execute("SELECT chat_id FROM chats"):CHAT_IDS.add(row[0])
    c.commit();c.close()

def save_chat(cid):
    CHAT_IDS.add(cid)
    c=sqlite3.connect("betting.db");c.execute("INSERT OR IGNORE INTO chats(chat_id) VALUES(?)",(cid,));c.commit();c.close()

def api_get(ep):
    try:
        r=requests.get(f"{API_BASE}{ep}",headers=HEADERS,timeout=15)
        return r.json() if r.status_code==200 else {}
    except:return{}

def get_fixtures():
    today=datetime.now().strftime("%Y-%m-%d")
    out=[]
    for code,name in COMPETITIONS.items():
        data=api_get(f"/competitions/{code}/matches?dateFrom={today}&dateTo={today}&status=SCHEDULED")
        for m in data.get("matches",[]):
            home=m.get("homeTeam",{});away=m.get("awayTeam",{})
            out.append({"fixture_id":m.get("id"),"competition":code,"league_name":name,"home_id":home.get("id"),"home_name":home.get("name",""),"away_id":away.get("id"),"away_name":away.get("name",""),"date":m.get("utcDate","")})
    return out

def get_form(team_id,competition):
    data=api_get(f"/teams/{team_id}/matches?competitions={competition}&status=FINISHED&limit=5")
    ms=data.get("matches",[])
    form=""
    for m in ms[-5:]:
        home=m.get("homeTeam",{});away=m.get("awayTeam",{})
        score=m.get("score",{}).get("fullTime",{})
        hg=score.get("home",0)or 0;ag=score.get("away",0)or 0
        ih=home.get("id")==team_id
        if ih:form+="V" if hg>ag else("E" if hg==ag else "D")
        else:form+="V" if ag>hg else("E" if hg==ag else "D")
    return form or "----"

def analyse(team_id,competition):
    data=api_get(f"/teams/{team_id}/matches?competitions={competition}&status=FINISHED&limit=10")
    ms=data.get("matches",[])
    if not ms:return{}
    s=defaultdict(lambda:{"w":0,"t":0})
    for m in ms:
        home=m.get("homeTeam",{});away=m.get("awayTeam",{})
        score=m.get("score",{}).get("fullTime",{});ht=m.get("score",{}).get("halfTime",{})
        ih=home.get("id")==team_id
        hg=score.get("home",0)or 0;ag=score.get("away",0)or 0;tot=hg+ag
        hth=ht.get("home",0)or 0;hta=ht.get("away",0)or 0;htt=hth+hta
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
        s["over05_ht"]["t"]+=1
        if htt>0:s["over05_ht"]["w"]+=1
    return{k:v["w"]/v["t"] for k,v in s.items() if v["t"]>=3}

def conf_label(wr):
    if wr>=0.75:return"🔥 Alta"
    if wr>=0.65:return"⚡ Média"
    return"💧 Baixa"

def best_market(team_id,competition,is_home):
    r=analyse(team_id,competition)
    if not r:return"over25",0.55
    ex=["away_win"] if is_home else["home_win"]
    v={k:w for k,w in r.items() if k not in ex}
    if not v:return"over25",0.55
    b=max(v.items(),key=lambda x:x[1]);return b

def top_markets(team_id,competition,is_home,n=3):
    r=analyse(team_id,competition)
    if not r:return[("over25",0.55)]
    ex=["away_win"] if is_home else["home_win"]
    v=[(k,w) for k,w in r.items() if k not in ex]
    v.sort(key=lambda x:x[1],reverse=True)
    return v[:n]

def hora_angola(date_str):
    try:
        dt=datetime.fromisoformat(date_str.replace("Z","+00:00"))
        from datetime import timezone,timedelta
        angola=timezone(timedelta(hours=1))
        return dt.astimezone(angola).strftime("%H:%M")
    except:return""

def gen_simples(fixtures):
    cands=[]
    for f in fixtures:
        mh,wh=best_market(f["home_id"],f["competition"],True)
        ma,wa=best_market(f["away_id"],f["competition"],False)
        if wh>=wa:mk,wr=mh,wh
        else:mk,wr=ma,wa
        odd=round(MARKET_ODDS.get(mk,1.85)*(0.85 if wr>=0.75 else 0.92 if wr>=0.65 else 1.0),2)
        form_h=get_form(f["home_id"],f["competition"])
        form_a=get_form(f["away_id"],f["competition"])
        cands.append({**f,"market":mk,"market_name":MARKETS.get(mk,mk),"win_rate":wr,"odd":odd,"form_h":form_h,"form_a":form_a,"confianca":conf_label(wr),"mercados":[{"market":mk,"market_name":MARKETS.get(mk,mk),"odd":odd,"win_rate":wr}]})
    cands.sort(key=lambda x:x["win_rate"],reverse=True)
    bil=[];oa=1.0
    for c in cands:
        if len(bil)>=9:break
        if oa*c["odd"]<=75:bil.append(c);oa*=c["odd"]
        if oa>=30:break
    for c in cands:
        if oa>=30:break
        if c not in bil and len(bil)<9:bil.append(c);oa*=c["odd"]
    if not bil:return None
    return{"jogos":bil,"odd_total":round(oa,2),"criado_em":datetime.now().isoformat(),"tipo":"simples"}

def gen_construcao(fixtures):
    cands=[]
    for f in fixtures:
        mkts_h=top_markets(f["home_id"],f["competition"],True,3)
        mkts_a=top_markets(f["away_id"],f["competition"],False,3)
        all_mkts={k:v for k,v in mkts_h+mkts_a}
        top=sorted(all_mkts.items(),key=lambda x:x[1],reverse=True)[:3]
        if not top:continue
        odd_jogo=1.0
        mercados=[]
        for mk,wr in top:
            o=round(MARKET_ODDS.get(mk,1.85)*(0.85 if wr>=0.75 else 0.92 if wr>=0.65 else 1.0),2)
            odd_jogo=round(odd_jogo*o,2)
            mercados.append({"market":mk,"market_name":MARKETS.get(mk,mk),"odd":o,"win_rate":wr})
        avg_wr=sum(w for _,w in top)/len(top)
        form_h=get_form(f["home_id"],f["competition"])
        form_a=get_form(f["away_id"],f["competition"])
        cands.append({**f,"odd":odd_jogo,"win_rate":avg_wr,"form_h":form_h,"form_a":form_a,"confianca":conf_label(avg_wr),"mercados":mercados,"market_name":" + ".join(m["market_name"] for m in mercados)})
    cands.sort(key=lambda x:x["win_rate"],reverse=True)
    bil=[];oa=1.0
    for c in cands:
        if len(bil)>=5:break
        if oa*c["odd"]<=200:bil.append(c);oa*=c["odd"]
        if oa>=30:break
    if not bil:return None
    return{"jogos":bil,"odd_total":round(oa,2),"criado_em":datetime.now().isoformat(),"tipo":"construcao"}

def fmt_bilhete(b,bid=None):
    tipo=b.get("tipo","simples")
    emoji="🎯" if tipo=="simples" else"🏗️"
    L=[f"{emoji} *BILHETE {'SIMPLES' if tipo=='simples' else 'COM CONSTRUÇÃO'}*"]
    if bid:L.append(f"🔖 ID: #{bid}")
    L.append(f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')} 🇦🇴")
    L.append("━"*28)
    for i,j in enumerate(b["jogos"],1):
        hora=hora_angola(j.get("date",""))
        L.append(f"*{i}.* {j['league_name']}")
        L.append(f"   ⚽ {j['home_name']} vs {j['away_name']}")
        L.append(f"   📊 Forma: `{j.get('form_h','---')}` vs `{j.get('form_a','---')}`")
        if tipo=="construcao":
            L.append(f"   🏗️ *Construção:*")
            for m in j.get("mercados",[]):
                L.append(f"      • {m['market_name']} ({round(m['win_rate']*100)}%) @ `{m['odd']}`")
            L.append(f"   💰 Odd jogo: `{j['odd']}`")
        else:
            L.append(f"   📈 {j['market_name']} | {j['confianca']} ({round(j.get('win_rate',0)*100)}%)")
            L.append(f"   💰 Odd: `{j['odd']}`" + (f" 🕐 {hora}" if hora else""))
        L.append("")
    L.append("━"*28)
    L.append(f"💥 *ODD TOTAL: {b['odd_total']}x*")
    L.append("⚠️ _Aposte com responsabilidade_")
    return"\n".join(L)

def save_bilhete(b):
    cn=sqlite3.connect("betting.db");cur=cn.cursor()
    cur.execute("INSERT INTO bilhetes(criado_em,jogos,odd_total,tipo) VALUES(?,?,?,?)",(b["criado_em"],json.dumps(b["jogos"]),b["odd_total"],b.get("tipo","simples")))
    bid=cur.lastrowid;cn.commit();cn.close();return bid

async def start(u,c):
    save_chat(u.message.chat_id)
    kb=[[InlineKeyboardButton("🎯 Bilhete Simples",callback_data="simples")],[InlineKeyboardButton("🏗️ Bilhete Construção",callback_data="construcao")],[InlineKeyboardButton("📋 Jogos Hoje",callback_data="jogos")],[InlineKeyboardButton("📜 Histórico",callback_data="historico")]]
    await u.message.reply_text("⚽ *Betting Tips Bot*\n\n🇦🇴 Olá! Analiso estatísticas de 10 ligas e gero bilhetes inteligentes!\n\n🎯 *Simples* — 1 mercado por jogo\n🏗️ *Construção* — vários mercados por jogo\n\nEscolhe:",reply_markup=InlineKeyboardMarkup(kb),parse_mode="Markdown")

async def cb(u,c):
    q=u.callback_query;await q.answer();save_chat(q.message.chat_id)
    if q.data in("simples","construcao"):
        m=await q.message.reply_text("⏳ A analisar e gerar bilhete...")
        await _gerar(q.message.chat_id,m,c,q.data)
    elif q.data=="jogos":
        await q.message.reply_text("⏳ A buscar jogos...")
        fx=get_fixtures()
        if not fx:await q.message.reply_text("❌ Sem jogos hoje.");return
        L=[f"📅 *Jogos Hoje ({len(fx)})*\n"]
        for f in fx[:15]:
            hora=hora_angola(f.get("date",""))
            L.append(f"🏆 {f['league_name']}\n⚽ {f['home_name']} vs {f['away_name']}" + (f" 🕐 {hora}" if hora else"")+"\n")
        await q.message.reply_text("\n".join(L),parse_mode="Markdown")
    elif q.data=="historico":
        cn=sqlite3.connect("betting.db");cur=cn.cursor()
        rows=cur.execute("SELECT id,criado_em,odd_total,tipo FROM bilhetes ORDER BY id DESC LIMIT 5").fetchall();cn.close()
        if not rows:await q.message.reply_text("📭 Sem bilhetes ainda.");return
        L=["📜 *Últimos Bilhetes*\n"]
        for r in rows:
            tipo_emoji="🎯" if r[3]=="simples" else"🏗️"
            L.append(f"{tipo_emoji} #{r[0]} | {r[1][:16].replace('T',' ')} | {r[2]}x")
        await q.message.reply_text("\n".join(L),parse_mode="Markdown")
    elif q.data.startswith("novo_"):
        tipo=q.data.replace("novo_","")
        m=await q.message.reply_text("⏳ A gerar novo bilhete...")
        await _gerar(q.message.chat_id,m,c,tipo)

async def _gerar(cid,msg,c,tipo="simples"):
    try:
        fx=get_fixtures()
        if not fx:await c.bot.edit_message_text("❌ Sem jogos hoje.",chat_id=cid,message_id=msg.message_id);return
        b=gen_simples(fx) if tipo=="simples" else gen_construcao(fx)
        if not b:await c.bot.edit_message_text("❌ Não foi possível gerar bilhete.",chat_id=cid,message_id=msg.message_id);return
        bid=save_bilhete(b)
        kb=[[InlineKeyboardButton(f"🔄 Novo {'Simples' if tipo=='simples' else 'Construção'}",callback_data=f"novo_{tipo}"),InlineKeyboardButton("📋 Jogos",callback_data="jogos")],[InlineKeyboardButton("🎯 Simples" if tipo=="construcao" else"🏗️ Construção",callback_data="simples" if tipo=="construcao" else"construcao")]]
        await c.bot.edit_message_text(fmt_bilhete(b,bid),chat_id=cid,message_id=msg.message_id,parse_mode="Markdown",reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await c.bot.edit_message_text(f"❌ Erro: {str(e)[:150]}",chat_id=cid,message_id=msg.message_id)

async def envio_automatico(context):
    fx=get_fixtures()
    if not fx:return
    b=gen_simples(fx)
    if not b:return
    bid=save_bilhete(b)
    texto=f"🌅 *BOM DIA! Bilhete do Dia* 🇦🇴\n\n"+fmt_bilhete(b,bid)
    for cid in list(CHAT_IDS):
        try:await context.bot.send_message(chat_id=cid,text=texto,parse_mode="Markdown")
        except:pass

def main():
    init_db()
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CallbackQueryHandler(cb))
    app.job_queue.run_daily(envio_automatico,time=time(8,0,0),name="daily_bilhete")
    log.info("Bot iniciado!")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":main()
