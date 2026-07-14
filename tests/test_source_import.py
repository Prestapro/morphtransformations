"""Tests for exact source-page preservation."""
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source_import import import_epub, import_docx


def _zip_xml(path, files):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_epub_preserves_document_sections(tmp_path):
    path = tmp_path / 'book.epub'
    _zip_xml(path, {
        'OEBPS/ch1.xhtml': '<html><body><h1>Глава I</h1><p>Текст.</p></body></html>',
        'OEBPS/ch2.xhtml': '<html><body><h1>Глава II</h1><p>Далее.</p></body></html>',
    })
    result = import_epub(path)
    assert [section['source_section'] for section in result.sections] == ['OEBPS/ch1.xhtml', 'OEBPS/ch2.xhtml']
    assert result.sections[0]['text'].startswith('Глава I')


def test_docx_preserves_explicit_page_breaks(tmp_path):
    path = tmp_path / 'book.docx'
    xml = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>Первая страница</w:t></w:r></w:p>
      <w:p><w:r><w:br w:type="page"/></w:r></w:p>
      <w:p><w:r><w:t>Вторая страница</w:t></w:r></w:p>
    </w:body></w:document>'''
    _zip_xml(path, {'word/document.xml': xml})
    result = import_docx(path)
    assert [section['page'] for section in result.sections] == [1, 2]
    assert result.sections[1]['text'] == 'Вторая страница'
