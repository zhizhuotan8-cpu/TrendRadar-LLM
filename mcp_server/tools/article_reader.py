"""MCP compatibility adapter for the shared article reader."""

from trendradar.intelligence.article_reader import ArticleReader


class ArticleReaderTools(ArticleReader):
    """Preserves the existing MCP single and batch response contracts."""
