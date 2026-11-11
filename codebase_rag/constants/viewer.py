# The interactive HTML graph viewer `cgr export -o graph.html` writes.

VIEWER_SUFFIX = ".html"
VIEWER_PACKAGE = "codebase_rag.viewer"
VIEWER_TEMPLATE = "graph_view.html"
VIEWER_DEFAULT_TITLE = "Code graph"

# Memgraph's Orb (Apache-2.0), the renderer Memgraph Lab is built on. Pinned
# with a subresource-integrity hash so a changed file on the CDN is refused
# rather than run against the user's graph. To bump: download the npm
# tarball, and hash dist/browser/orb.min.js with
# `openssl dgst -sha384 -binary orb.min.js | openssl base64 -A`.
VIEWER_ORB_VERSION = "1.1.0"
VIEWER_ORB_URL = (
    f"https://unpkg.com/@memgraph/orb@{VIEWER_ORB_VERSION}/dist/browser/orb.min.js"
)
VIEWER_ORB_SRI = (
    "sha384-P2jpPR0PRaYiw2OqRETE4Fo0WQpItZyXSTy88EeFZHB0mXtoDAWt8FcZVEd8dDLM"
)

VIEWER_PLACEHOLDER_TITLE = "__CGR_TITLE__"
VIEWER_PLACEHOLDER_DATA = "__CGR_GRAPH_DATA__"
VIEWER_PLACEHOLDER_ORB_URL = "__CGR_ORB_URL__"
VIEWER_PLACEHOLDER_ORB_SRI = "__CGR_ORB_SRI__"

# A canvas force layout stays responsive to a few thousand nodes; past that
# the page keeps the most connected ones and says so.
VIEWER_MAX_NODES = 5000
# Docstrings are shown in the side panel, not searched; a cap keeps a large
# export's file size dominated by the graph rather than by prose.
VIEWER_MAX_DOC_CHARS = 600

VIEWER_KEY_ID = "id"
VIEWER_KEY_LABEL = "label"
VIEWER_KEY_NAME = "name"
VIEWER_KEY_QN = "qn"
VIEWER_KEY_PATH = "path"
VIEWER_KEY_START = "start"
VIEWER_KEY_END = "end"
VIEWER_KEY_DOC = "doc"
VIEWER_KEY_SOURCE = "s"
VIEWER_KEY_TARGET = "t"
VIEWER_KEY_KIND = "k"
VIEWER_KEY_TITLE = "title"
VIEWER_KEY_META = "meta"
VIEWER_KEY_EDGES = "edges"
VIEWER_KEY_TRUNCATED = "truncated"
VIEWER_KEY_SHOWN_NODES = "shown_nodes"
VIEWER_KEY_PROJECTS = "projects"
VIEWER_PROJECT_LABEL = "Project"

# JSON inside a <script> element ends at the first "</script"; escaping these
# characters keeps any string in the graph (a docstring, a file name) from
# closing the element or opening a comment. U+2028/U+2029 are line breaks to
# older JavaScript parsers.
VIEWER_SCRIPT_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    " ": "\\u2028",
    " ": "\\u2029",
}
