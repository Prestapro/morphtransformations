"""Exact-boundary importers for PDF, EPUB and DOCX sources."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET


@dataclass
class ImportedSource:
    text: str
    sections: list[dict] = field(default_factory=list)
    source_format: str = ''


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        value = data.strip()
        if value:
            self.parts.append(value)


def import_epub(path: str | Path) -> ImportedSource:
    sections = []
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(('.xhtml', '.html', '.htm'))]
        for index, name in enumerate(names, 1):
            parser = _TextParser()
            parser.feed(archive.read(name).decode('utf-8', errors='replace'))
            text = '\n'.join(parser.parts)
            if text:
                sections.append({'page': None, 'section': index, 'source_section': name, 'text': text})
    return ImportedSource('\n\n'.join(s['text'] for s in sections), sections, 'epub')


def import_docx(path: str | Path) -> ImportedSource:
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    sections, current, page = [], [], 1
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    for paragraph in root.findall('.//w:p', ns):
        words = [node.text or '' for node in paragraph.findall('.//w:t', ns)]
        text = ''.join(words).strip()
        if text:
            current.append(text)
        page_break = any(br.get('{%s}type' % ns['w']) == 'page' for br in paragraph.findall('.//w:br', ns))
        if page_break:
            if current:
                sections.append({'page': page, 'section': page, 'source_section': 'word/document.xml', 'text': '\n'.join(current)})
                current = []
            page += 1
    if current:
        sections.append({'page': page, 'section': page, 'source_section': 'word/document.xml', 'text': '\n'.join(current)})
    return ImportedSource('\n\n'.join(s['text'] for s in sections), sections, 'docx')


def import_pdf(path: str | Path) -> ImportedSource:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError('PDF import requires pypdf') from exc
    sections = []
    for page_number, page in enumerate(PdfReader(str(path)).pages, 1):
        text = (page.extract_text() or '').strip()
        sections.append({'page': page_number, 'section': page_number, 'source_section': f'page:{page_number}', 'text': text})
    return ImportedSource('\n\n'.join(s['text'] for s in sections if s['text']), sections, 'pdf')
