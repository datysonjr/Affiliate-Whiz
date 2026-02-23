"""
core.utils.text
~~~~~~~~~~~~~~~

Text processing utilities for the OpenClaw content pipeline.

Provides functions for slugifying titles, truncating text for meta
descriptions, stripping HTML, counting words, and computing keyword
density -- all essential for SEO-optimized content generation and
quality checks.

Usage::

    from src.core.utils.text import slugify, truncate, strip_html, word_count, keyword_density

    slug = slugify("Best Wireless Headphones Under $100!")
    meta = truncate(article_body, max_length=155)
    plain = strip_html("<p>Hello <b>world</b></p>")
    wc = word_count(article_body)
    kd = keyword_density(article_body, "wireless headphones")
"""

from __future__ import annotations

import html
import re
import unicodedata


# =====================================================================
# Slugification
# =====================================================================

def slugify(text: str, max_length: int = 80, separator: str = "-") -> str:
    """Convert text to a URL-safe slug.

    Handles Unicode by transliterating to ASCII, strips non-alphanumeric
    characters, collapses whitespace, and enforces a maximum length
    (breaking at word boundaries when possible).

    Parameters
    ----------
    text:
        Raw text to slugify (e.g. an article title).
    max_length:
        Maximum character length of the resulting slug.
    separator:
        Character used between words (default ``"-"``).

    Returns
    -------
    str
        URL-safe slug string.

    Examples
    --------
    >>> slugify("Best Wireless Headphones Under $100!")
    'best-wireless-headphones-under-100'
    >>> slugify("Cafe Latte & Espresso", max_length=15)
    'cafe-latte'
    """
    # Normalize Unicode to ASCII approximation
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    # Lowercase and strip
    text = text.lower().strip()

    # Replace non-alphanumeric characters with the separator
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", separator, text)
    text = text.strip(separator)

    # Enforce max length, breaking at word boundary if possible
    if len(text) > max_length:
        truncated = text[:max_length]
        last_sep = truncated.rfind(separator)
        if last_sep > max_length // 2:
            truncated = truncated[:last_sep]
        text = truncated.rstrip(separator)

    return text


# =====================================================================
# Truncation
# =====================================================================

def truncate(
    text: str,
    max_length: int = 155,
    suffix: str = "...",
    break_on_word: bool = True,
) -> str:
    """Truncate text to a maximum length, optionally at word boundaries.

    Designed for generating meta descriptions and social media excerpts
    where a clean cut-off matters for readability.

    Parameters
    ----------
    text:
        Text to truncate.
    max_length:
        Maximum total length including the suffix.
    suffix:
        String appended when truncation occurs.
    break_on_word:
        If ``True``, break at the last space before the limit rather
        than cutting mid-word.

    Returns
    -------
    str
        Truncated text, at most *max_length* characters.

    Examples
    --------
    >>> truncate("The quick brown fox jumps over the lazy dog", max_length=20)
    'The quick brown...'
    >>> truncate("Short", max_length=20)
    'Short'
    """
    if len(text) <= max_length:
        return text

    limit = max_length - len(suffix)
    if limit <= 0:
        return suffix[:max_length]

    truncated = text[:limit]

    if break_on_word:
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]

    return truncated.rstrip() + suffix


# =====================================================================
# HTML stripping
# =====================================================================

def strip_html(html_text: str) -> str:
    """Remove HTML tags and decode entities, returning plain text.

    Handles common HTML constructs: tags, comments, CDATA sections,
    style/script blocks, and named/numeric entities.

    Parameters
    ----------
    html_text:
        HTML string to strip.

    Returns
    -------
    str
        Plain text with HTML removed and whitespace normalized.

    Examples
    --------
    >>> strip_html("<p>Hello <b>world</b></p>")
    'Hello world'
    >>> strip_html("<script>alert('x')</script>Content")
    'Content'
    >>> strip_html("&amp; &lt;tag&gt;")
    '& <tag>'
    """
    # Remove script and style blocks entirely
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    clean = re.sub(r"<!--.*?-->", "", clean, flags=re.DOTALL)

    # Remove all remaining tags
    clean = re.sub(r"<[^>]+>", "", clean)

    # Decode HTML entities
    clean = html.unescape(clean)

    # Normalize whitespace
    clean = re.sub(r"\s+", " ", clean)

    return clean.strip()


# =====================================================================
# Word counting
# =====================================================================

def word_count(text: str) -> int:
    """Count the number of words in text.

    Strips HTML before counting, so both plain text and HTML input are
    accepted.

    Parameters
    ----------
    text:
        Text (or HTML) to count words in.

    Returns
    -------
    int
        Number of whitespace-separated tokens.

    Examples
    --------
    >>> word_count("Hello world, how are you?")
    5
    >>> word_count("<p>Hello <b>world</b></p>")
    2
    >>> word_count("")
    0
    """
    plain = strip_html(text)
    if not plain:
        return 0
    return len(plain.split())


# =====================================================================
# Keyword density
# =====================================================================

def keyword_density(text: str, keyword: str) -> float:
    """Calculate the density of a keyword phrase in text.

    Density is computed as::

        occurrences_of_keyword / total_word_count

    For multi-word keywords, the full phrase is matched (not individual
    words).  The count represents how many times the phrase appears,
    divided by the total number of words in the document.

    Parameters
    ----------
    text:
        The body text to analyze (HTML is stripped automatically).
    keyword:
        The keyword or keyphrase to search for (case-insensitive).

    Returns
    -------
    float
        Keyword density as a fraction (e.g. ``0.015`` for 1.5%).
        Returns ``0.0`` if the text is empty.

    Examples
    --------
    >>> keyword_density("buy the best shoes for the best price", "best")
    0.25
    >>> keyword_density("", "anything")
    0.0
    """
    plain = strip_html(text).lower()
    keyword_lower = keyword.lower().strip()

    if not plain or not keyword_lower:
        return 0.0

    words = plain.split()
    total_words = len(words)

    if total_words == 0:
        return 0.0

    keyword_words = keyword_lower.split()
    if len(keyword_words) == 1:
        # Single-word keyword: count exact word matches
        count = sum(1 for w in words if w.strip(".,!?;:\"'()[]") == keyword_lower)
    else:
        # Multi-word keyword: count phrase occurrences in joined text
        joined = " ".join(words)
        count = 0
        start = 0
        while True:
            idx = joined.find(keyword_lower, start)
            if idx == -1:
                break
            count += 1
            start = idx + 1

    return count / total_words


# =====================================================================
# Additional text utilities
# =====================================================================

def extract_sentences(text: str, max_sentences: int = 3) -> list[str]:
    """Extract the first N sentences from text.

    Useful for auto-generating meta descriptions or summaries from
    article body text.

    Parameters
    ----------
    text:
        Plain text to extract sentences from.
    max_sentences:
        Maximum number of sentences to return.

    Returns
    -------
    list[str]
        List of sentence strings.

    Examples
    --------
    >>> extract_sentences("First. Second! Third? Fourth.", max_sentences=2)
    ['First.', 'Second!']
    """
    plain = strip_html(text)
    # Split on sentence-ending punctuation followed by whitespace
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    return [s.strip() for s in sentences[:max_sentences] if s.strip()]


def normalize_whitespace(text: str) -> str:
    """Collapse all whitespace sequences to single spaces and strip.

    Parameters
    ----------
    text:
        Input text.

    Returns
    -------
    str
        Cleaned text with normalized whitespace.
    """
    return re.sub(r"\s+", " ", text).strip()


def count_characters(text: str, exclude_spaces: bool = False) -> int:
    """Count characters in text, optionally excluding spaces.

    Parameters
    ----------
    text:
        Input text.
    exclude_spaces:
        If ``True``, whitespace characters are not counted.

    Returns
    -------
    int
        Character count.
    """
    if exclude_spaces:
        return len(re.sub(r"\s", "", text))
    return len(text)
