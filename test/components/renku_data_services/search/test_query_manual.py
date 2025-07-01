"""Tests for the query manual."""

from textwrap import dedent

from markdown_it import MarkdownIt

from renku_data_services.search import query_manual


def test_create_manual() -> None:
    query_manual.manual_to_str()


## When editing the manual it is quicker to run this test and open the
## html file in the browser. It adds the (ugly :-)) swagger ui styles
## for a more realistic preview
# @pytest.mark.skip(reason="This is not really an automated test.")
def test_manual_html() -> None:
    md = MarkdownIt("commonmark", {"breaks": False, "html": True})
    html = md.render(query_manual.manual_to_str())
    page = dedent(f"""<!DOCTYPE html>
        <head>
        <link rel="stylesheet" href="https://dev.renku.ch/swagger/swagger-ui.css">
        </head>
        <body>
            <div id="swagger-ui" class="swagger-ui">
            <div class="wrapper">
            <section class="block col-12 block-desktop col-12-desktop">
            <div class="no-margin opblock-body opblock-description-wrapper">
            <div class="renderedMarkdown">
            {html}
            </div> </div> </section></div></div>
        </body>
        </html>
        """)
    with open("manual.html", "w") as f:
        f.write(page)
