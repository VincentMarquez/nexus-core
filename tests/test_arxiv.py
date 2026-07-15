from nexus.arxiv_client import normalize_arxiv_id, _parse_feed


SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <updated>2023-01-01T00:00:00Z</updated>
    <published>2017-06-12T00:00:00Z</published>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models...</summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
    <link href="https://arxiv.org/abs/1706.03762v7" rel="alternate" type="text/html"/>
    <link title="pdf" href="https://arxiv.org/pdf/1706.03762v7" rel="related" type="application/pdf"/>
    <arxiv:comment>12 pages</arxiv:comment>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""


def test_normalize_id():
    assert normalize_arxiv_id("https://arxiv.org/abs/1706.03762") == "1706.03762"
    assert normalize_arxiv_id("arXiv:1706.03762") == "1706.03762"
    assert normalize_arxiv_id("1706.03762v7") == "1706.03762v7"


def test_parse_feed():
    papers = _parse_feed(SAMPLE_FEED)
    assert len(papers) == 1
    p = papers[0]
    assert "1706.03762" in p.arxiv_id
    assert "Attention" in p.title
    assert p.authors[0] == "Ashish Vaswani"
    assert "cs.CL" in p.categories
    assert "pdf" in p.pdf_url
