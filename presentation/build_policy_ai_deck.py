from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt


OUT = Path(__file__).with_name("정책AI_최종발표_멘토링반영_20261104.pptx")
prs = Presentation()
prs.slide_width = Inches(13.333333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]

# One visual system for the entire pitch deck. No analytical file is read or changed.
NAVY = "0B1020"; NAVY2 = "121A31"; PANEL = "17213B"; WHITE = "F6F8FC"
MUTED = "AAB6CC"; BLUE = "5B8CFF"; CYAN = "37D6C0"; ORANGE = "FFB85C"
RED = "FF6B7A"; LINE = "2C3A59"; INK = "17213B"; PAPER = "F7F9FC"
FONT = "Noto Sans KR"

def rgb(hexv):
    hexv = hexv.lstrip("#")
    return RGBColor(int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16))

def add_text(slide, x, y, w, h, text, size=18, color=WHITE, bold=False, align=PP_ALIGN.LEFT,
             font=FONT, valign=MSO_ANCHOR.TOP, margin=0.03):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear(); tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    p = tf.paragraphs[0]
    p.text = text; p.alignment = align
    f = p.font; f.name = font; f.size = Pt(size); f.bold = bold; f.color.rgb = rgb(color)
    return box

def rect(slide, x, y, w, h, fill=PANEL, line=None, radius=True):
    shape = slide.shapes.add_shape(
        MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE if radius else MSO_AUTO_SHAPE_TYPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h)
    )
    shape.fill.solid(); shape.fill.fore_color.rgb = rgb(fill)
    shape.line.color.rgb = rgb(line or fill)
    if radius:
        shape.adjustments[0] = 0.08
    return shape

def line(slide, x1, y1, x2, y2, color=LINE, width=1.3, arrow=False):
    shp = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    shp.line.color.rgb = rgb(color); shp.line.width = Pt(width)
    if arrow:
        shp.line.end_arrowhead = True
    return shp

def bg(slide, dark=True, page=None, section="POLICY AI"):
    rect(slide, 0, 0, 13.333, 7.5, NAVY if dark else PAPER, NAVY if dark else PAPER, False)
    if dark:
        rect(slide, 0.48, 0.42, 0.08, 0.20, CYAN, CYAN, False)
        add_text(slide, 0.68, 0.38, 3.2, 0.28, section, 9, CYAN, True)
        line(slide, 0.48, 6.94, 12.84, 6.94, LINE, 0.75)
        if page:
            add_text(slide, 12.32, 7.05, 0.5, 0.22, f"{page:02d}", 9, MUTED, True, PP_ALIGN.RIGHT)
    else:
        rect(slide, 0.48, 0.42, 0.08, 0.20, BLUE, BLUE, False)
        add_text(slide, 0.68, 0.38, 3.2, 0.28, section, 9, BLUE, True)
        line(slide, 0.48, 6.94, 12.84, 6.94, "D5DDEA", 0.75)
        if page:
            add_text(slide, 12.32, 7.05, 0.5, 0.22, f"{page:02d}", 9, "70809A", True, PP_ALIGN.RIGHT)

def title(slide, text, subtitle=None, page=None, dark=True):
    bg(slide, dark, page)
    c = WHITE if dark else INK
    add_text(slide, 0.62, 0.90, 11.8, 0.56, text, 27, c, True)
    if subtitle:
        add_text(slide, 0.64, 1.52, 11.4, 0.42, subtitle, 12, MUTED if dark else "59677F")

def pill(slide, x, y, w, text, color=BLUE, text_color=NAVY):
    rect(slide, x, y, w, 0.35, color, color)
    add_text(slide, x, y + 0.035, w, 0.20, text, 9, text_color, True, PP_ALIGN.CENTER)

def card(slide, x, y, w, h, label, value, detail, accent=BLUE, dark=True):
    fill = PANEL if dark else WHITE
    rect(slide, x, y, w, h, fill, LINE if dark else "DDE5F1")
    rect(slide, x, y, 0.06, h, accent, accent, False)
    add_text(slide, x+0.22, y+0.18, w-0.38, 0.22, label, 10, MUTED if dark else "67758D", True)
    add_text(slide, x+0.22, y+0.52, w-0.38, 0.46, value, 23, WHITE if dark else INK, True)
    add_text(slide, x+0.22, y+1.06, w-0.38, h-1.18, detail, 10, MUTED if dark else "59677F")

def footer_source(slide, text, dark=True):
    add_text(slide, 0.64, 6.98, 10.9, 0.22, "자료: " + text, 7.5, MUTED if dark else "75839A")

def bullet(slide, x, y, text, color=WHITE, dot=CYAN, size=13, width=5.6):
    rect(slide, x, y+0.12, 0.10, 0.10, dot, dot, False)
    add_text(slide, x+0.20, y, width-0.20, 0.36, text, size, color)

def node(slide, x, y, label, fill=BLUE, w=1.10, h=0.47):
    rect(slide, x, y, w, h, fill, fill)
    add_text(slide, x, y+0.09, w, 0.20, label, 11, NAVY, True, PP_ALIGN.CENTER)

# 01 Cover
s = prs.slides.add_slide(BLANK)
bg(s, True, 1, "FINAL PRESENTATION · POLICY AI")
pill(s, 0.64, 1.02, 1.60, "2026 FINAL", CYAN)
add_text(s, 0.64, 1.60, 11.3, 1.15, "회의록에서 정책 이슈를\n읽는 순서를 만드는 AI", 33, WHITE, True)
add_text(s, 0.68, 3.02, 8.6, 0.48, "최초 관측 · 지역 흐름 · 참조 근거 · 검토 우선순위를 하나의 화면으로", 16, MUTED)
for i, (v, lab, col) in enumerate([("17", "광역의회", BLUE), ("6", "정책 이슈", CYAN), ("14,176", "최종 관측", ORANGE)]):
    card(s, 0.68+i*2.2, 4.22, 1.95, 1.30, lab, v, "2024–2025 제공 자료", col)
rect(s, 9.35, 1.42, 2.94, 3.88, PANEL, LINE)
add_text(s, 9.72, 1.80, 2.15, 0.30, "ONE-LINE PROMISE", 10, CYAN, True)
add_text(s, 9.72, 2.24, 2.12, 1.66, "‘채택 확률’이 아니라\n무엇을 먼저 읽을지\n근거와 함께 보여줍니다.", 17, WHITE, True)
line(s, 9.72, 4.08, 11.86, 4.08, LINE)
add_text(s, 9.72, 4.30, 2.15, 0.62, "관측 기반 탐색 도구\n인과·채택을 단정하지 않음", 10, MUTED)
footer_source(s, "2024–2025 광역의회 회의록 · 최종 파이프라인 산출물")

# 02 problem
s = prs.slides.add_slide(BLANK); title(s, "회의록은 많지만, 정책 흐름은 한눈에 보이지 않습니다", "자료를 더 모으는 문제가 아니라 ‘근거가 연결된 읽기 순서’의 문제입니다.", 2)
items = [
    ("FIND", "시작을 찾기 어렵다", "수백만 개 청크 속에서 이슈의\n제공 자료 내 최초 관측을 찾기 어렵습니다."),
    ("CONNECT", "지역 간 언급이 흩어져 있다", "다른 지역의 사례를 참고한 발언이\n원문·일자와 분리되어 있습니다."),
    ("PRIORITIZE", "어디부터 읽을지 막막하다", "논의량·최근성·참조·근거를\n함께 보고 검토 순서를 정해야 합니다."),
]
for i,(tag, head, detail) in enumerate(items):
    x=0.70+i*4.10; rect(s,x,2.30,3.66,2.60,PANEL,LINE)
    pill(s,x+0.26,2.58,1.05,tag,CYAN if i==0 else BLUE)
    add_text(s,x+0.26,3.13,3.0,0.36,head,18,WHITE,True)
    add_text(s,x+0.26,3.73,3.05,0.70,detail,12,MUTED)
add_text(s,0.72,5.52,11.6,0.42,"그래서 Track-AI는 ‘예측’을 단정하지 않고, 회의록 원문으로 되돌아갈 수 있는 탐색·검토 화면을 만듭니다.",15,CYAN,True)

# 03 solution/use case
s = prs.slides.add_slide(BLANK); title(s, "하나의 질문을 다섯 번의 확인으로 바꿉니다", "이슈 선택 → 지역 흐름 → 참조 관계 → 원문 → 검토 우선순위", 3)
steps=[("01","이슈 선택","6개 이슈 중 하나를 고릅니다."),("02","지역 흐름","월별 논의량과 지역별 지수를 봅니다."),("03","참조 관계","출처 → 참조 의회 방향과 근거 등급을 봅니다."),("04","원문 확인","일자·회의록·발언자·청크 ID로 되돌아갑니다."),("05","검토 순서","점수와 가중치로 다음 원문을 정합니다.")]
for i,(n,h,d) in enumerate(steps):
    x=.62+i*2.50; rect(s,x,2.42,2.12,2.30,PANEL,LINE)
    add_text(s,x+.18,2.68,1.62,.25,n,10,CYAN,True)
    add_text(s,x+.18,3.16,1.72,.45,h,15,WHITE,True)
    add_text(s,x+.18,3.84,1.70,.55,d,10,MUTED)
    if i<4: line(s,x+2.12,3.56,x+2.40,3.56,CYAN,1.5,True)
rect(s,.68,5.46,11.88,.66,"14213B",LINE)
add_text(s,.92,5.66,11.35,.22,"중요: 지수는 채택 확률이 아니라 ‘원문 검토 우선순위’이며, 참조 화살표는 인과적 확산을 증명하지 않습니다.",11,ORANGE,True)

# 04 scope / proof
s = prs.slides.add_slide(BLANK); title(s, "과장 대신, 관측 범위와 한계를 먼저 고정했습니다", "분석 결과를 바꾸지 않고도 신뢰도 높은 시연은 가능합니다.", 4)
for i,(lab,val,detail,col) in enumerate([
    ("분석 범위","2024–2025","17개 광역의회 제공 회의록",BLUE),
    ("전처리","3,756,820","화자·문단으로 분리한 청크",CYAN),
    ("최종 관측","14,176","6개 이슈의 근거 연결 관측",ORANGE),
    ("지수 행","102","6개 이슈 × 17개 지역",RED),
]): card(s,.68+i*3.08,2.32,2.78,1.58,lab,val,detail,col)
rect(s,.68,4.44,5.78,1.48,PANEL,LINE); add_text(s,.96,4.72,5.12,.26,"우리가 말하는 것",11,CYAN,True); bullet(s,.96,5.12,"제공 자료 안의 최초 관측과 논의 흐름",width=5.0); bullet(s,.96,5.45,"원문 근거가 연결된 참조 단서와 검토 순서",width=5.0)
rect(s,6.76,4.44,5.78,1.48,PANEL,LINE); add_text(s,7.04,4.72,5.12,.26,"우리가 말하지 않는 것",11,ORANGE,True); bullet(s,7.04,5.12,"정책 채택 확률·정책 효과·인과적 확산",dot=ORANGE,width=5.0); bullet(s,7.04,5.45,"제공 기간 이전의 실제 정책 기원",dot=ORANGE,width=5.0)
footer_source(s,"최종 관측 CSV · 대시보드 내장 데이터")

# 05 pipeline
s = prs.slides.add_slide(BLANK); title(s,"후보를 넓게 찾고, 근거를 좁게 확인하는 7단계", "NMF는 후보 탐색, 최종 관측은 검색·규칙·사람 검수를 결합한 결과입니다.", 5)
pipe=[("01","전처리","화자·문단 분리"),("02","NMF","이슈 후보 탐색"),("03","FTS5·E5","근거 검색"),("04","최초 관측","정책 단계 분류"),("05","NetworkX","참조 그래프"),("06","준비 지수","6×17 = 102행"),("07","보고서","근거형 결과")]
for i,(n,h,d) in enumerate(pipe):
    x=.55+i*1.80; rect(s,x,2.62,1.46,1.72,PANEL,LINE)
    add_text(s,x+.14,2.84,1.1,.20,n,9,CYAN,True)
    add_text(s,x+.14,3.23,1.12,.35,h,12,WHITE,True)
    add_text(s,x+.14,3.74,1.10,.30,d,8.5,MUTED)
    if i<6: line(s,x+1.46,3.48,x+1.72,3.48,BLUE,1.2,True)
add_text(s,.70,5.10,11.80,.34,"1,114,422개 NMF 적격 세그먼트 → 토픽 후보 20개 → 6개 이슈 최종 관측 14,176건",16,WHITE,True,PP_ALIGN.CENTER)
add_text(s,.72,5.68,11.72,.26,"분석 파이프라인·집계 기준·점수 산식은 변경하지 않았습니다. 이번 발표본은 결과를 읽는 순서만 개선합니다.",10,ORANGE,False,PP_ALIGN.CENTER)
footer_source(s,"전처리·NMF·검색·최종 파이프라인 산출물")

# 06 search
s = prs.slides.add_slide(BLANK); title(s,"검색은 FTS5를 기본으로, E5·RRF는 비교 실험으로 분리했습니다", "‘무엇이 더 좋아 보이는가’보다, 사람 검수로 확인한 근거를 우선했습니다.", 6)
cols=[("FTS5 · BM25","기본 검색 채택","이슈명·별칭의 키워드 일치와 정책 문맥을 상단에 올립니다.",CYAN), ("E5 · Cosine","보조 검색","같은 단어가 없어도 의미가 가까운 문장을 후보로 찾습니다.",BLUE), ("RRF · k=60","비교 실험","점수가 아닌 순위만 결합했습니다. 기본값으로 채택하지 않았습니다.",ORANGE)]
for i,(h,b,d,c) in enumerate(cols):
    x=.72+i*4.12; rect(s,x,2.30,3.62,2.32,PANEL,LINE); pill(s,x+.24,2.58,1.15,"STEP " + str(i+1),c); add_text(s,x+.24,3.11,3.02,.30,h,16,WHITE,True); add_text(s,x+.24,3.53,3.04,.22,b,10,c,True); add_text(s,x+.24,3.92,3.00,.48,d,10,MUTED)
rect(s,.72,5.16,11.86,.76,"14213B",LINE); add_text(s,.98,5.36,2.20,.24,"사람 검수",11,CYAN,True); add_text(s,3.05,5.30,2.0,.30,"52 / 60",20,WHITE,True); add_text(s,5.04,5.36,6.84,.24,"FTS5 Top-10 표본의 Precision@10 = 86.7% · 재현율은 전수 정답 집합이 없어 미측정",10,MUTED)
footer_source(s,"이슈별 FTS Top-10 사람 검수 60건 · 검색 모델 코드")

# 07 first observation
s = prs.slides.add_slide(BLANK); title(s,"‘최초’는 결론이 아니라, 원문으로 들어가는 문입니다", "석유화학·철강산업 위기대응 이슈의 제공 자료 내 최초 관측 사례", 7)
rect(s,.72,2.22,3.10,3.34,"14213B",LINE); add_text(s,1.02,2.58,2.48,.24,"FIRST OBSERVED",10,CYAN,True); add_text(s,1.02,3.08,2.34,.44,"2024-12-11",23,WHITE,True); add_text(s,1.02,3.72,2.44,.68,"전남 · 기획행정위원회\n제386회(7차)",11,MUTED); add_text(s,1.02,4.70,2.42,.45,"발언자 김종기\n청크 ID …T0002_01",10,MUTED)
rect(s,4.14,2.22,8.12,3.34,PANEL,LINE); add_text(s,4.52,2.58,6.90,.25,"원문 근거",11,CYAN,True); add_text(s,4.52,3.20,6.92,1.08,"“또 석유화학산업 위기극복을 위해 산업위기 선제대응지역 지정, 세제감면.”",21,WHITE,True); line(s,4.52,4.64,11.70,4.64,LINE); add_text(s,4.52,4.93,6.98,.28,"회의록명 · 일자 · 화자 · 청크 ID까지 연결해 재확인할 수 있습니다.",11,MUTED)
add_text(s,.74,5.92,11.64,.25,"‘최초’는 제공된 2024–2025 자료 범위 내 최초 관측이며, 정책의 실제 기원을 뜻하지 않습니다.",10,ORANGE,True,PP_ALIGN.CENTER)
footer_source(s,"석유화학·철강산업 위기대응 · 최종 관측 CSV")

# 08 network graph
s = prs.slides.add_slide(BLANK); title(s,"참조 그래프는 ‘출처 → 참조한 의회’의 원문 단서입니다", "NetworkX MultiDiGraph · 화살표는 명시적 참조 또는 시간 단서이며 인과적 확산의 증명은 아닙니다.", 8)
rect(s,.65,2.12,7.52,3.92,"0F1830",LINE)
node(s,1.10,3.50,"인천",CYAN); node(s,2.62,2.64,"전남",BLUE); node(s,4.45,2.62,"충북",ORANGE); node(s,5.95,3.50,"충남",RED)
line(s,2.18,3.55,2.62,2.98,CYAN,2.0,True); line(s,3.72,2.88,4.45,2.88,BLUE,2.0,True); line(s,5.55,2.98,5.95,3.55,ORANGE,2.0,True)
add_text(s,2.26,3.16,.36,.28,"↗",18,CYAN,True,PP_ALIGN.CENTER); add_text(s,3.88,2.64,.34,.28,"→",18,BLUE,True,PP_ALIGN.CENTER); add_text(s,5.56,3.16,.36,.28,"↘",18,ORANGE,True,PP_ALIGN.CENTER)
add_text(s,1.00,4.48,6.75,.25,"사례 경로: 인천 → 전남 → 충북 → 충남",11,WHITE,True,PP_ALIGN.CENTER)
add_text(s,1.00,4.86,6.75,.40,"충북 → 충남: 2025-02-19 · ‘충북 등을 벤치마킹…’",10,MUTED,False,PP_ALIGN.CENTER)
card(s,8.54,2.14,1.72,1.28,"참조 사건","85","이슈별 엣지",CYAN); card(s,10.48,2.14,1.72,1.28,"고유 지역쌍","50","방향 중복 제거",BLUE)
card(s,8.54,3.68,1.72,1.28,"추정 경로","20","시간 근거 포함",ORANGE); card(s,10.48,3.68,1.72,1.28,"명시 참조","21","인과 미확정",CYAN)
rect(s,8.54,5.34,3.66,.56,"14213B",LINE); add_text(s,8.78,5.51,3.16,.20,"참조 후보 44건 · 인과 확정 0건",9.5,ORANGE,True,PP_ALIGN.CENTER)
footer_source(s,"NetworkX MultiDiGraph · 참조 방향 그래프 산출물")

# 09 index
s = prs.slides.add_slide(BLANK); title(s,"확산 준비 지수는 ‘무엇을 먼저 읽을지’ 정하는 0–100점입니다", "정책 채택 확률도, 미래 예측 정확도도 아닙니다. 이슈 안에서만 비교합니다.", 9)
add_text(s,.76,2.23,11.7,.48,"Index = S₃₀ + I₂₅ + T₂₀ + R₂₀ + C₅",28,WHITE,True,PP_ALIGN.CENTER)
parts=[("S","정책 단계",30,"가장 진행된 정책 단계",CYAN),("I","관측 강도",25,"논의량 로그 정규화",BLUE),("T","최근 논의",20,"최근 180일 비중",ORANGE),("R","유입 참조",20,"다른 지역에서 받은 참조",RED),("C","근거 완전성",5,"완전한 근거 비율",CYAN)]
for i,(letter,h,pts,d,c) in enumerate(parts):
    x=.72+i*2.44; rect(s,x,3.30,2.08,1.72,PANEL,LINE); add_text(s,x+.18,3.56,.42,.32,letter,21,c,True); add_text(s,x+.66,3.60,1.15,.22,h,11,WHITE,True); add_text(s,x+.18,4.15,1.72,.34,str(pts)+"점",18,WHITE,True); add_text(s,x+.18,4.66,1.72,.22,d,8.5,MUTED)
rect(s,.72,5.58,11.90,.56,"14213B",LINE); add_text(s,.94,5.75,11.42,.20,"R은 ‘해당 지역이 언급한 수’가 아니라, 다른 지역에서 받은 유입 참조 수입니다.",10,ORANGE,True,PP_ALIGN.CENTER)
footer_source(s,"확산 준비 지수 산출 코드(S·I·T·R·C 합산) · 102행")

# 10 demo
s = prs.slides.add_slide(BLANK); title(s,"시연은 ‘클릭’이 아니라 ‘질문에 답하는 흐름’으로 진행합니다", "약 90초: 인구감소 사례에서 원문까지 도달하는 과정을 보여 줍니다.", 10)
demo=[("1","이슈 선택","인구감소·지역소멸",CYAN),("2","지역 확인","충남 · 검토 우선순위 2위",BLUE),("3","그래프 클릭","충북 → 충남 추정 경로",ORANGE),("4","원문 확인","회의일자·회의록명·발언 원문",RED),("5","가중치 조정","참조를 중시할 때 순위 변화",CYAN)]
for i,(n,h,d,c) in enumerate(demo):
    y=2.10+i*.72; rect(s,.72,y,.52,.46,c,c); add_text(s,.72,y+.11,.52,.18,n,10,NAVY,True,PP_ALIGN.CENTER); add_text(s,1.48,y+.04,2.05,.22,h,12,WHITE,True); add_text(s,3.78,y+.04,5.55,.32,d,11,MUTED); line(s,9.58,y+.23,10.16,y+.23,c,1.5,True)
rect(s,10.34,2.10,2.02,3.36,"14213B",LINE); add_text(s,10.60,2.42,1.50,.25,"시연 원칙",11,CYAN,True); bullet(s,10.60,2.92,"차트는 현황",width=1.45,size=10); bullet(s,10.60,3.37,"화살표는 단서",width=1.45,size=10); bullet(s,10.60,3.82,"원문은 근거",width=1.45,size=10); bullet(s,10.60,4.27,"점수는 순서",width=1.45,size=10)
add_text(s,.74,6.00,11.55,.22,"백업: 브라우저 문제 시 전체 화면 캡처 또는 실행 영상으로 같은 클릭 순서를 설명합니다.",10,ORANGE,False,PP_ALIGN.CENTER)

# 11 validation
s = prs.slides.add_slide(BLANK); title(s,"검수는 모델의 ‘정답률’이 아니라, 현재 결과의 신뢰 범위를 보여줍니다", "좋은 결과만 제시하지 않고, 측정한 것과 아직 측정하지 않은 것을 분리했습니다.", 11)
card(s,.76,2.35,2.72,1.68,"검색 정밀도","86.7%","FTS5 Top-10 · 52 / 60\n사람 검수 표본",CYAN)
card(s,3.75,2.35,2.72,1.68,"사람 검수","127행","2인 검수 고유 행\n규칙 개선에 활용",BLUE)
card(s,6.74,2.35,2.72,1.68,"기각","21건","관측 10 · 참조 11\n오탐으로 제거",ORANGE)
card(s,9.73,2.35,2.72,1.68,"단계 수정","36건","정책 단계 표현\n규칙 보수화",RED)
rect(s,.76,4.62,11.69,1.15,"14213B",LINE); add_text(s,1.05,4.89,2.08,.22,"정직한 해석",11,ORANGE,True); add_text(s,3.22,4.83,8.62,.52,"수정 후 규칙의 독립 새 표본 측정은 아직 없습니다.\n따라서 발표에서는 이를 ‘향후 검증 과제’로 명시합니다.",12,WHITE,True)
footer_source(s,"사람 검수 127행 · 이슈별 FTS Top-10 검수 60건")

# 12 boundaries
s = prs.slides.add_slide(BLANK); title(s,"이 대시보드가 하는 일과 하지 않는 일을 분명히 구분합니다", "이 구분이 결과의 과장을 막고, 실제 정책 담당자의 검토에 맞는 도구가 되게 합니다.", 12)
left=["제공 자료 내 최초 관측을 찾는다","지역별 논의 흐름과 원문을 연결한다","명시 참조·시간 단서를 방향 그래프로 보인다","우선적으로 읽을 회의록을 정한다"]
right=["정책 채택을 예측하지 않는다","참조 화살표로 인과를 확정하지 않는다","회의록 밖의 실제 행정 완료를 증명하지 않는다","사람 검수를 자동으로 대체하지 않는다"]
rect(s,.72,2.25,5.72,3.38,"14213B",LINE); add_text(s,1.02,2.56,4.95,.26,"CAN · 근거 기반 탐색",12,CYAN,True)
for i,t in enumerate(left): bullet(s,1.02,3.06+i*.53,t,width=4.95)
rect(s,6.85,2.25,5.72,3.38,"14213B",LINE); add_text(s,7.15,2.56,4.95,.26,"CANNOT · 단정하지 않는 영역",12,ORANGE,True)
for i,t in enumerate(right): bullet(s,7.15,3.06+i*.53,t,dot=ORANGE,width=4.95)
footer_source(s,"최종 관측·참조 그래프·확산 준비 지수의 해석 범위")

# 13 delivery
s = prs.slides.add_slide(BLANK); title(s,"완성도는 ‘더 많은 기능’보다, 같은 결과를 재현해 보이는 데 있습니다", "발표에서는 구현 범위를 한 문장씩, 증빙과 함께 말합니다.", 13)
rows=[("분석","6개 이슈 · 17개 광역의회 · 14,176개 최종 관측","원문·청크 ID까지 추적",CYAN),("검색","FTS5 기본 · E5 보조 · RRF 비교","사람 검수 52/60",BLUE),("참조","NetworkX MultiDiGraph · 85개 사건","인과 확정 0건을 명시",ORANGE),("시연","이슈 → 지역 → 그래프 → 원문 → 지수","브라우저 백업 화면 준비",RED)]
for i,(a,b,c,d) in enumerate(rows):
    y=2.06+i*.84; rect(s,.75,y,11.76,.62,PANEL,LINE); pill(s,.98,y+.13,1.05,a,d); add_text(s,2.28,y+.14,5.78,.22,b,11,WHITE,True); add_text(s,8.18,y+.14,3.88,.22,c,10,MUTED)
rect(s,.75,5.78,11.76,.58,"14213B",LINE); add_text(s,1.00,5.96,11.26,.20,"발표 문구에서는 ‘최종 결과’와 ‘향후 검증’을 구분하고, [확인 필요]·내부 자문 문구를 남기지 않습니다.",10,ORANGE,True,PP_ALIGN.CENTER)

# 14 roadmap
s = prs.slides.add_slide(BLANK); title(s,"다음 버전의 목표는 점수를 더 높이는 것이 아니라 검증 범위를 넓히는 것입니다", "현재의 한계는 숨기지 않고, 검증 가능한 다음 단계로 분리합니다.", 14)
road=[("NOW","근거형 대시보드","6개 이슈 · 원문 연결 · 검토 우선순위",CYAN),("NEXT","독립 새 표본 검수","수정 후 규칙의 정밀도·재현율 재측정",BLUE),("THEN","시간 외부검증","기간을 나눈 실제 시행·채택 라벨 검토",ORANGE),("LATER","운영 피드백","담당자 검토 이력으로 근거 품질 고도화",RED)]
for i,(tag,h,d,c) in enumerate(road):
    x=.64+i*3.12; rect(s,x,2.50,2.64,2.48,PANEL,LINE); pill(s,x+.22,2.78,.78,tag,c); add_text(s,x+.22,3.45,2.05,.40,h,15,WHITE,True); add_text(s,x+.22,4.10,2.03,.48,d,10,MUTED)
    if i<3: line(s,x+2.64,3.74,x+2.98,3.74,c,1.7,True)
add_text(s,.72,5.70,11.75,.26,"현재 결과를 바꾸지 않습니다. 다음 실험은 새 데이터·사전 등록된 기준으로 별도 검증합니다.",11,ORANGE,True,PP_ALIGN.CENTER)

# 15 close
s = prs.slides.add_slide(BLANK); bg(s,True,15,"FINAL PRESENTATION · POLICY AI")
pill(s,.70,1.06,1.78,"CLOSING",CYAN)
add_text(s,.70,1.75,10.9,1.10,"회의록의 ‘양’을\n근거가 있는 ‘읽는 순서’로 바꿉니다.",31,WHITE,True)
add_text(s,.74,3.43,9.9,.38,"최초 관측 · 지역 흐름 · 참조 단서 · 원문 근거 · 검토 우선순위",15,MUTED)
rect(s,.74,4.48,11.76,.95,"14213B",LINE); add_text(s,1.04,4.76,11.10,.34,"정책 채택 확률을 단정하지 않고도, 담당자가 더 빠르고 투명하게 근거를 확인하도록 돕습니다.",15,CYAN,True,PP_ALIGN.CENTER)
add_text(s,.74,5.96,10.3,.26,"감사합니다 · 질의응답",14,WHITE,True)

# Appendix A1
s = prs.slides.add_slide(BLANK); title(s,"[부록] 이슈별 해석 규칙", "본문에서 생략한 방법론의 경계와 용어를 확인할 수 있습니다.", 16, True)
rows=[("최초 관측","제공된 2024–2025 회의록 범위 내 최초 · 정책의 실제 기원 아님"),("관측","회의록 발언 단위 관측 · 정책 도입 건수 아님"),("참조","출처 지역 → 참조한 의회 · 인과적 확산의 증명 아님"),("준비 지수","이슈 내부의 검토 순서 · 채택 확률·이슈 간 비교 아님")]
for i,(a,b) in enumerate(rows):
    y=2.10+i*.77; rect(s,.78,y,11.68,.57,PANEL,LINE); add_text(s,1.06,y+.16,2.05,.20,a,11,CYAN,True); add_text(s,3.28,y+.16,8.62,.20,b,10.5,WHITE)

# Appendix A2
s = prs.slides.add_slide(BLANK); title(s,"[부록] 대표 사례 원문", "인구감소·지역소멸: 인천 → 전남 → 충북 → 충남", 17, True)
case=[("2024-01-16","인천","학령인구 감소로 인한 … 현실적인 어려움이 있어"),("2024-01-23","전남","지방소멸대응기금 사업인데 … 사업계획서를 내야 됩니다."),("2025-02-19","충남","충북 등을 벤치마킹하여 우리 충남도 출산율이 증가할 수 있는 …")]
for i,(d,r,q) in enumerate(case):
    x=.72+i*4.10; rect(s,x,2.30,3.60,2.75,PANEL,LINE); add_text(s,x+.22,2.60,2.86,.22,d,11,CYAN,True); add_text(s,x+.22,3.03,2.86,.28,r,17,WHITE,True); add_text(s,x+.22,3.64,2.86,.70,"“"+q+"”",10.5,MUTED)
add_text(s,.74,5.75,11.4,.26,"충북 → 충남은 시간 근거 추정 경로이며, 참조·시간 선후만으로 인과를 확정하지 않습니다.",10,ORANGE,True,PP_ALIGN.CENTER)

# Appendix A3
s = prs.slides.add_slide(BLANK); title(s,"[부록] 지수 계산식", "구성 항목의 의미와 산식은 코드에 구현된 기본값을 그대로 표시합니다.", 18, True)
formula=[("S₃₀","30 × max_stage / 6","가장 진행된 정책 단계"),("I₂₅","25 × log(1+observation_count) / log(1+issue_max_count)","관측 건수의 로그 정규화"),("T₂₀","20 × recent_180d_count / observation_count","최근 180일 관측 비중"),("R₂₀","20 × log(1+incoming_reference_count) / log(1+issue_max_reference_count)","유입 참조 수의 로그 정규화"),("C₅","5 × complete_evidence_count / observation_count","근거 완전성 비율")]
for i,(a,b,c) in enumerate(formula):
    y=1.92+i*.72; rect(s,.72,y,11.85,.53,PANEL,LINE); add_text(s,.95,y+.14,.55,.20,a,12,CYAN,True); add_text(s,1.72,y+.14,6.65,.20,b,10,WHITE); add_text(s,8.72,y+.14,3.20,.20,c,9.5,MUTED)
add_text(s,.72,5.92,11.74,.30,"항목별 최댓값은 30·25·20·20·5이며, 코드에서 별도 clip 없이 합산합니다.",10,ORANGE,True,PP_ALIGN.CENTER)

# Appendix A4
s = prs.slides.add_slide(BLANK); title(s,"[부록] 시연 운영 체크리스트", "온라인 연결 없이도 발표의 핵심 흐름을 유지하기 위한 준비", 19, True)
checks=[("A","브라우저","최종 HTML 단일 파일을 로컬에서 열고, 이슈·지역·가중치 조작 확인"),("B","그래프","노드·선 클릭 → 날짜·회의록명·원문 카드 연결 확인"),("C","백업","전체 화면 캡처 및 실행 영상 준비"),("D","발표","이슈 → 지역 → 참조 → 원문 → 지수 순서로 90초 시연")]
for i,(a,b,c) in enumerate(checks):
    y=2.06+i*.80; rect(s,.82,y,.50,.50,CYAN,CYAN); add_text(s,.82,y+.13,.50,.20,a,11,NAVY,True,PP_ALIGN.CENTER); add_text(s,1.62,y+.07,2.10,.22,b,13,WHITE,True); add_text(s,3.72,y+.07,8.10,.35,c,10.5,MUTED)
add_text(s,.82,5.78,11.52,.26,"데이터·분석 코드·모델·검수 판정·점수 산식은 수정하지 않습니다.",10,ORANGE,True,PP_ALIGN.CENTER)

for slide in prs.slides:
    # Disable presentation autofit changes by leaving explicit font sizes and fixed boxes.
    for shape in slide.shapes:
        if hasattr(shape, "text_frame"):
            for paragraph in shape.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.name = FONT

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(OUT)
