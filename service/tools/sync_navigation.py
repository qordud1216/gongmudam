"""Render the same sidebar links in every app page, without runtime duplication."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GROUPS = [
    ('업무 공간', [('start.html', '⌂', '업무 시작'), ('index.html#chat', '◇', '서무 안내'),
     ('folders.html', '▱', '업무자료 정리'), ('adhoc.html#inbox', '▤', '자료 취합'),
     ('travel.html', '↗', '출장정산')]),
    ('자료 관리', [('index.html#home', '⌂', '업무 현황'), ('index.html#cards', '▤', '업무 절차 카드'),
     ('index.html#docs', '▦', '규정·지침·서식'), ('index.html#forms', '▣', '서식 칸 정의'),
     ('adhoc.html#templates', '▦', '기관 취합 서식')]),
    ('관리 · 설정', [('travel.html#organizations', '⚙', '기관 설정'),
     ('index.html#settings', '⚙', '모델 설정'), ('local-ai.html', '◉', '로컬 AI 검증')]),
]

def render(page):
    index = page == 'index.html'
    chunks = ['<nav class="sb-mid common-navigation" aria-label="주 메뉴">' if index else '<nav class="common-navigation" aria-label="주 메뉴">']
    for group_index,(title, links) in enumerate(GROUPS):
        if group_index==1:chunks.append('<details class="navigation-settings"><summary>관리 · 설정</summary>')
        if group_index:chunks.append(f'<small class="sb-section-hd">{title}</small>')
        for href, icon, label in links:
            attrs = ''
            if index and href.startswith('index.html#'):
                attrs = f' data-view="{href.split("#")[1]}"'
            if page == 'travel.html' and href.startswith('travel.html'):
                attrs = f' data-page="{href.split("#")[1] if "#" in href else "settle"}"'
            active = href == page or page=='adhoc.html' and href=='adhoc.html#inbox' or page=='change-inbox.html' and href=='folders.html'
            chunks.append(f'<a class="{"sb-item" if index else "nav"}{" active" if active else ""}" href="{href}"{attrs}><span class="{"sb-item-ico" if index else "nav-icon"}" aria-hidden="true">{icon}</span><span>{label}</span></a>')
    return ''.join(chunks) + '</details></nav>'

def sync(root=ROOT/'static'):
    for path in root.glob('*.html'):
        text = path.read_text(encoding='utf-8-sig')
        if not re.search(r'<aside\b[^>]*(?:class="sidebar"|id="sidebar")', text):
            continue
        text, count = re.subn(r'(<aside\b[^>]*>[\s\S]*?)<nav\b[^>]*>[\s\S]*?</nav>', lambda m: m[1]+render(path.name), text, count=1)
        if count != 1:
            raise ValueError(f'Missing sidebar: {path}')
        if path.name == 'travel.html':
            toolbar = '<nav id="travel-tools" class="toolbar" aria-label="출장 세부 도구"><a class="secondary" href="#settle" data-page="settle">정산 준비</a><a class="secondary" href="#history" data-page="history">저장한 출장</a><a class="secondary" href="#rules" data-page="rules">계산 근거</a><a class="secondary" href="#demo" data-page="demo">시연 사례</a></nav>'
            if 'id="travel-tools"' in text:text=re.sub(r'<nav id="travel-tools"[\s\S]*?</nav>',toolbar,text,count=1)
            else:text = text.replace('<main>', '<main>'+toolbar, 1)
        path.write_text(text, encoding='utf-8')

if __name__ == '__main__':
    sync()
