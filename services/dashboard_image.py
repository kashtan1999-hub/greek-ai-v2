"""Premium live learner dashboard rendered from durable database statistics."""
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parents[1] / 'assets' / 'fonts'
TEAL = '#087f8c'
INK = '#163c45'
MUTED = '#59727a'
GREEN = '#2d9d5c'
RED = '#c74747'
LIGHT = '#edf6f7'


def render_dashboard(p):
    im = Image.new('RGB', (1200, 1760), LIGHT)
    d = ImageDraw.Draw(im)
    def font(size, bold=False):
        return ImageFont.truetype(str(FONT_DIR / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')), size)
    def text(x, y, value, size=24, color=INK, bold=False):
        d.text((x, y), str(value), font=font(size, bold), fill=color)
    def card(x, y, w, h, fill='white'):
        d.rounded_rectangle((x, y, x+w, y+h), radius=24, fill=fill)
    def bar(x, y, w, value, total=100):
        d.rounded_rectangle((x, y, x+w, y+20), radius=10, fill='#dfecef')
        ratio=max(0, min(1, float(value or 0)/max(float(total or 1), 1)))
        if ratio:
            d.rounded_rectangle((x, y, x+max(20, w*ratio), y+20), radius=10, fill=TEAL)

    state=p.get('state') or {}
    status=str(p.get('subscription_status') or 'unknown').lower()
    active=status=='active'
    status_label='АКТИВНА' if active else {'free':'БЕСПЛАТНЫЙ ДЕМО','past_due':'ТРЕБУЕТ ОПЛАТЫ'}.get(status,status.upper())
    status_color=GREEN if active else RED if status in {'past_due','canceled','unpaid'} else MUTED
    current_block=state.get('current_block') or '1.1'
    topic=str(state.get('current_topic') or 'Не начато')
    lesson_progress=int(state.get('lesson_progress') or 0)
    course_progress=float(p.get('percent') or 0)

    text(50,35,'ВАШ ПРОГРЕСС',36,bold=True)
    text(50,92,f"Греческий язык  ·  {p.get('date_label','Сегодня')}  ·  {p.get('timezone','Europe/Athens')}",23,MUTED)

    # KPI cards
    values=[
        ('Слов в верных ответах',p.get('words',0),'Сохранённые правильные ответы'),
        ('Завершено уроков',p.get('completed',0),f"Из {p.get('total_lessons',35)} уроков курса"),
        ('Ответов сегодня',p.get('today',0),f"AI-диалогов: {p.get('ai_turns_today',0)}"),
        ('Доступ к курсу',status_label,f"Оплачено до: {str(p.get('billing_period_end') or '—')[:10]}"),
    ]
    for i,(label,value,note) in enumerate(values):
        x=50+(i%2)*560; y=145+(i//2)*180
        card(x,y,540,160); text(x+25,y+18,label,24,MUTED); text(x+25,y+55,value,43,bold=True,color=status_color if label=='Доступ к курсу' else INK); text(x+25,y+117,note,18,MUTED)

    # Current lesson — deliberately prominent/live.
    card(50,515,1100,170)
    text(75,535,'СЕЙЧАС УЧИТСЯ',18,TEAL,bold=True)
    text(75,565,f'Урок {current_block}',32,bold=True)
    topic_short=topic
    while d.textlength(topic_short,font=font(21))>650: topic_short=topic_short[:-4]+'…'
    text(75,610,topic_short,21,MUTED)
    text(825,565,f'{lesson_progress}%',36,TEAL,bold=True)
    text(825,610,f"Шаг {state.get('current_step') or 1} · Взаимодействий {state.get('interaction_number') or 0}",18,MUTED)
    bar(75,650,1050,lesson_progress,100)

    # Daily goal + live activity
    card(50,705,540,155); card(610,705,540,155)
    text(75,725,'ЦЕЛЬ НА СЕГОДНЯ',22,bold=True)
    goal=max(1,int(p.get('goal') or 10)); today=int(p.get('today') or 0)
    text(75,762,f'{today} / {goal} ответов',25)
    text(430,762,f'{min(100,round(today/goal*100))}%',23,TEAL)
    bar(75,812,465,today,goal)
    text(635,725,'ЖИВАЯ АКТИВНОСТЬ',22,bold=True)
    text(635,762,f"{p.get('interactions_today',0)} взаимодействий",27,bold=True)
    text(635,805,f"AI: {p.get('ai_turns_today',0)}  ·  Ответы: {today}",19,MUTED)

    # Seven-day graph + assessments
    card(50,880,540,330); card(610,880,540,330)
    text(75,902,'АКТИВНОСТЬ ЗА 7 ДНЕЙ',24,bold=True)
    data=p.get('daily_activity',[]); maximum=max([v.get('count',0) for v in data]+[1])
    base_y=1128
    for i,row in enumerate(data):
        x=92+i*68; h=(row.get('count',0)/maximum)*155
        if h: d.rounded_rectangle((x,base_y-h,x+35,base_y),radius=6,fill=TEAL)
        text(x-1,base_y-h-27,row.get('count',0),17,MUTED)
        text(x-5,1145,row.get('label',''),15,MUTED)
    if not data: text(90,1030,'Пока нет активности',21,MUTED)

    text(635,902,'РЕЗУЛЬТАТЫ ОЦЕНКИ',24,bold=True)
    text(635,940,f"{p.get('tests',0)} завершено · {p.get('passed',0)} пройдено",19,MUTED)
    scores=p.get('recent_scores',[])
    for i,row in enumerate(scores):
        y=980+i*40; text(635,y,row.get('label','Тест'),19,MUTED); bar(785,y+2,210,row.get('score',0),100); text(1010,y,f"{row.get('score',0)}%",18)
    if not scores: text(635,1010,'Пока нет результатов',21,MUTED)

    # Course overview
    card(50,1230,1100,190)
    text(75,1250,'ОБЩИЙ ПРОГРЕСС КУРСА',27,bold=True)
    text(75,1295,f"Уровень {state.get('level') or 'A1'}  ·  Блок {current_block}  ·  Курс {course_progress}%",23)
    text(75,1334,f"Пройдено: {p.get('completed',0)}/{p.get('total_lessons',35)}  ·  Закреплено: {p.get('retained',0)}",19,MUTED)
    bar(75,1372,1050,course_progress,100)

    # Learning history / mistakes
    card(50,1445,1100,250)
    text(75,1465,'УЧЕБНАЯ ИСТОРИЯ И ПОВТОРЕНИЕ',26,bold=True)
    text(75,1508,f"Серия: {p.get('streak',0)} дн. · Ошибок: {p.get('open_mistakes',0)} · Повторить: {p.get('review_due',0)}",21,MUTED)
    rows=p.get('recent_history',[])[:3]
    for i,row in enumerate(rows):
        y=1550+i*42; label=f"{str(row.get('created_at',''))[:10]} · {row.get('block','')} · {row.get('topic','')} · {row.get('score','—')}%"
        while d.textlength(label,font=font(18))>1030: label=label[:-5]+'…'
        text(75,y,label,18)
    if not rows: text(75,1555,'История появится после завершённых уроков и оценок.',20,MUTED)
    text(50,1718,'Все показатели берутся из сохранённых данных и обновляются при открытии панели.',18,MUTED)
    result=BytesIO(); im.save(result,format='PNG'); return result.getvalue()
