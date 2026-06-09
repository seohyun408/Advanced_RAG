import re
import fitz  # PyMuPDF (pip install pymupdf)
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

HEADING_FONT_SIZE = 11.0     # 섹션 헤딩 폰트 크기 (본문 9.3, 푸터 10.6, 헤딩 11.3)
SECTION_NUM_RE = re.compile(r'^\d+(\.\d+)*\.$')  # 1. / 1.1. / 1.1.1. 매칭
TOC_PAGES = 5                # 앞 5페이지(표지+면책+목차) 스킵

def extract_sections(pdf_path: str, skip_pages: int = TOC_PAGES):
    """
    PyMuPDF span 레벨에서 폰트 크기로 섹션 헤딩을 감지해 섹션을 추출한다.
    헤딩은 size>=11.0인 스팬이 '번호 스팬 → 제목 스팬' 순서로 연속 등장하는 패턴.
    반환: (sections, all_headings)
      - sections    : 본문이 있는 섹션 목록
      - all_headings: {num: title} – 본문 없는 중간 헤딩까지 포함한 전체 헤딩 dict
    """
    doc = fitz.open(pdf_path)
    sections: list = []
    all_headings: dict = {}                                      # breadcrumb용 전체 헤딩
    current = {"num": "0", "title": "머리말", "content": "", "start_page": 1}
    pending_num = None

    for page_idx in range(skip_pages, len(doc)):
        page = doc[page_idx]
        for block in page.get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    size = span["size"]
                    if not text:
                        continue

                    if size >= HEADING_FONT_SIZE:
                        if SECTION_NUM_RE.match(text):
                            pending_num = text                   # e.g. "1.1."
                        elif pending_num is not None:
                            num_clean = pending_num.rstrip(".")
                            all_headings[num_clean] = text       # 중간 헤딩 포함 전체 기록
                            if current["content"].strip():
                                sections.append(current.copy())
                            current = {
                                "num": num_clean,
                                "title": text,
                                "content": "",
                                "start_page": page_idx + 1,
                            }
                            pending_num = None
                        else:
                            pending_num = None
                    elif size > 10.0:
                        pending_num = None                       # 푸터(10.6) 스킵
                    else:
                        pending_num = None
                        current["content"] += text + "\n"

    if current["content"].strip():
        sections.append(current)

    return sections, all_headings


def get_breadcrumb(num: str, all_headings: dict) -> str:
    """
    '2.1.1' → '소유권보존등기 > 토지소유권보존등기 > 개념및신청인'
    부모 헤딩이 누락된 레벨은 건너뛴다.
    """
    parts = num.split(".")
    crumbs = []
    for i in range(len(parts)):
        prefix = ".".join(parts[: i + 1])
        if prefix in all_headings:
            crumbs.append(all_headings[prefix])
    return " > ".join(crumbs)


def get_breadcrumb_for_page(page_num: int, sections: list, all_headings: dict) -> tuple:
    """
    페이지 번호 → (section_num, breadcrumb) 반환.
    start_page <= page_num 인 섹션 중 가장 마지막 섹션을 사용.
    """
    active = None
    for s in sorted(sections, key=lambda x: x["start_page"]):
        if s["start_page"] <= page_num:
            active = s
        else:
            break
    if active is None:
        return "", ""
    num = active["num"]
    return num, get_breadcrumb(num, all_headings)

