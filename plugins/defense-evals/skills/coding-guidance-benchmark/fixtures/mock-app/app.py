"""Fixed code for the mock harnesses' scoring-path check (framework Python-Flask).

It starts a web server on port 5000 and answers every request with 404. It implements no
task, so BaxBench should build it, start it, and fail its functional tests. That is the
point: it proves code reaches BaxBench's test mode and a result comes back.
"""
from flask import Flask

app = Flask(__name__)


@app.errorhandler(404)
def not_found(_error):
    return {"error": "not implemented"}, 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
