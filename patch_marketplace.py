import re

file_path = "piclaw-os/piclaw/tools/marketplace.py"
with open(file_path, "r") as f:
    content = f.read()

# Add pre-compiled regexes right after the imports
imports_end = content.find("\n\n# ── Seen-IDs verwalten")
if imports_end == -1:
    print("Could not find import section end")

compiled_regexes = """

# ── Pre-compiled Regular Expressions ──────────────────────────────────────────

# Query Cleaning
RE_CLEAN_CHAT_PREFIX = re.compile(r"\[.*?\]")
RE_CLEAN_PLZ = re.compile(r"(?<!\d)\d{5}(?!\d)")
RE_CLEAN_RADIUS = re.compile(r"\d+\s*km", flags=re.IGNORECASE)
RE_CLEAN_PLATFORMS = {
    term: re.compile(re.escape(term), flags=re.IGNORECASE)
    for term in ["kleinanzeigen.de", "ebay.de", "kleinanzeigen", "ebay", ".de"]
}
RE_CLEAN_NOISE = []
noise_words = ["suche", "finde", "such", "find", "schau", "schaue", "durchsuche",
         "zeig", "liste", "was kostet", "preis für", "gibt es", "schnäppchen",
         "angebot", "umkreis", "radius", "einen", "eine", "ein", "mir",
         "dem", "der", "die", "das", "bitte", "im", "in", "um", "von", "bis",
         "nähe", "für", "unter", "euro", "rosengarten", "hamburg", "berlin",
         "nach", "mit", "den", "auf", "mal", "einem", "einer", "münchen",
         "frankfurt", "düsseldorf", "köln", "hannover", "leipzig", "bremen",
         "kaufen", "verkaufen", "preis", "günstig", "billig", "suche", "verkaufe",
         "bitte", "gerade", "aktuell", "inserate", "anzeigen"]
noise_words.sort(key=len, reverse=True)
for word in noise_words:
    RE_CLEAN_NOISE.append(re.compile(r"(?i)(?:^|(?<=\W))" + re.escape(word) + r"(?:(?=\W)|$)"))
RE_CLEAN_SPECIAL_CHARS = re.compile(r"[?!.,;:\-_/]")

# Common Parsing
RE_HTML_TAGS = re.compile(r'<[^>]+>')
RE_PARSE_PRICE = re.compile(r"(\d+(?:\.\d+)?)")

# Kleinanzeigen Parsing
RE_KA_ARTICLES = re.compile(r'<article[^>]+data-adid="(\d+)"[^>]*>(.*?)</article>', re.DOTALL)
RE_KA_TITLE_1 = re.compile(r'class="[^"]*text-module-begin[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>', re.DOTALL)
RE_KA_TITLE_2 = re.compile(r'<a[^>]*class="[^"]*ellipsis[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
RE_KA_PRICE = re.compile(r'<p[^>]*class="[^"]*aditem-main--middle--price[^"]*"[^>]*>(.*?)</p>', re.DOTALL)
RE_KA_LOCATION = re.compile(r'<span[^>]*class="[^"]*aditem-main--top--left[^"]*"[^>]*>(.*?)</span>', re.DOTALL)

# eBay Parsing
RE_EBAY_ITEMS_1 = re.compile(r'<li[^>]+data-view="[^"]*mi:1686[^"]*"[^>]*id="item(\d+)"[^>]*>(.*?)</li>', re.DOTALL)
RE_EBAY_ITEMS_2 = re.compile(r'<div[^>]+class="[^"]*s-item[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</li>', re.DOTALL)
RE_EBAY_TITLE_1 = re.compile(r'<span[^>]+role="heading"[^>]*>(.*?)</span>', re.DOTALL)
RE_EBAY_TITLE_2 = re.compile(r'class="[^"]*s-item__title[^"]*"[^>]*>(.*?)</[^>]+>', re.DOTALL)
RE_EBAY_PRICE = re.compile(r'class="[^"]*s-item__price[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
RE_EBAY_LINK = re.compile(r'href="(https://www\.ebay\.de/itm/[^"]+)"')

# Web Parsing
RE_WEB_HITS = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
RE_WEB_SNIPPETS = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)
"""

new_content = content[:imports_end] + compiled_regexes + content[imports_end:]

# Apply replacements for _clean_query
new_content = new_content.replace(
    'q = re.sub(r"\\[.*?\\]", " ", query)',
    'q = RE_CLEAN_CHAT_PREFIX.sub(" ", query)'
)
new_content = new_content.replace(
    'q = re.sub(r"(?<!\\d)\\d{5}(?!\\d)", " ", q)',
    'q = RE_CLEAN_PLZ.sub(" ", q)'
)
new_content = new_content.replace(
    'q = re.sub(r"\\d+\\s*km", " ", q, flags=re.IGNORECASE)',
    'q = RE_CLEAN_RADIUS.sub(" ", q)'
)
# We will use replace_with_git_merge_diff for the platform loop
# and the noise loop to make it cleaner

# Price parser
new_content = new_content.replace(
    'match = re.search(r"(\\d+(?:\\.\\d+)?)", text)',
    'match = RE_PARSE_PRICE.search(text)'
)

# Kleinanzeigen
new_content = new_content.replace(
    '''    articles = re.findall(
        r'<article[^>]+data-adid="(\\d+)"[^>]*>(.*?)</article>',
        html, re.DOTALL
    )''',
    '    articles = RE_KA_ARTICLES.findall(html)'
)
new_content = new_content.replace(
    '''        title_match = re.search(
            r'class="[^"]*text-module-begin[^"]*"[^>]*>\\s*<a[^>]*>(.*?)</a>',
            content, re.DOTALL
        )''',
    '        title_match = RE_KA_TITLE_1.search(content)'
)
new_content = new_content.replace(
    '''            title_match = re.search(r'<a[^>]*class="[^"]*ellipsis[^"]*"[^>]*>(.*?)</a>',
                                    content, re.DOTALL)''',
    '            title_match = RE_KA_TITLE_2.search(content)'
)
new_content = new_content.replace(
    '''        price_match = re.search(r'<p[^>]*class="[^"]*aditem-main--middle--price[^"]*"[^>]*>(.*?)</p>',
                                 content, re.DOTALL)''',
    '        price_match = RE_KA_PRICE.search(content)'
)
new_content = new_content.replace(
    '''        loc_match = re.search(r'<span[^>]*class="[^"]*aditem-main--top--left[^"]*"[^>]*>(.*?)</span>',
                               content, re.DOTALL)''',
    '        loc_match = RE_KA_LOCATION.search(content)'
)

# HTML Tag stripper (used everywhere)
new_content = new_content.replace(
    're.sub(r\'<[^>]+\>\', \' \', title_match.group(1))',
    'RE_HTML_TAGS.sub(\' \', title_match.group(1))'
)
new_content = new_content.replace(
    're.sub(r\'<[^>]+\>\', \' \', price_match.group(1))',
    'RE_HTML_TAGS.sub(\' \', price_match.group(1))'
)
new_content = new_content.replace(
    're.sub(r\'<[^>]+\>\', \' \', loc_match.group(1))',
    'RE_HTML_TAGS.sub(\' \', loc_match.group(1))'
)
new_content = new_content.replace(
    're.sub(r\'<[^>]+\>\', \'\', title)',
    'RE_HTML_TAGS.sub(\'\', title)'
)
new_content = new_content.replace(
    're.sub(r\'<[^>]+\>\', \'\', snippets[i])',
    'RE_HTML_TAGS.sub(\'\', snippets[i])'
)

# eBay
new_content = new_content.replace(
    '''    items = re.findall(
        r'<li[^>]+data-view="[^"]*mi:1686[^"]*"[^>]*id="item(\\d+)"[^>]*>(.*?)</li>',
        html, re.DOTALL
    )''',
    '    items = RE_EBAY_ITEMS_1.findall(html)'
)
new_content = new_content.replace(
    '''        items = re.findall(
            r'<div[^>]+class="[^"]*s-item[^"]*"[^>]*>(.*?)</div>\\s*</div>\\s*</li>',
            html, re.DOTALL
        )''',
    '        items = RE_EBAY_ITEMS_2.findall(html)'
)
new_content = new_content.replace(
    '''        title_match = re.search(
            r'<span[^>]+role="heading"[^>]*>(.*?)</span>',
            content, re.DOTALL
        )''',
    '        title_match = RE_EBAY_TITLE_1.search(content)'
)
new_content = new_content.replace(
    '''            title_match = re.search(r'class="[^"]*s-item__title[^"]*"[^>]*>(.*?)</[^>]+>',
                                    content, re.DOTALL)''',
    '            title_match = RE_EBAY_TITLE_2.search(content)'
)
new_content = new_content.replace(
    '''        price_match = re.search(r'class="[^"]*s-item__price[^"]*"[^>]*>(.*?)</span>',
                                 content, re.DOTALL)''',
    '        price_match = RE_EBAY_PRICE.search(content)'
)
new_content = new_content.replace(
    '''        link_match = re.search(r'href="(https://www\\.ebay\\.de/itm/[^"]+)"', content)''',
    '        link_match = RE_EBAY_LINK.search(content)'
)

# Web Search
new_content = new_content.replace(
    '''    hits = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )''',
    '    hits = RE_WEB_HITS.findall(html)'
)
new_content = new_content.replace(
    '''    snippets = re.findall(
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )''',
    '    snippets = RE_WEB_SNIPPETS.findall(html)'
)


with open(file_path, "w") as f:
    f.write(new_content)

print("Applied replacements")
