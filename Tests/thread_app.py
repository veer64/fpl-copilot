"""Test helper for Prompt B: main.app in a REAL process, offline (the brain of thread_fakes.py as the Anthropic client,
the logs and market lookups stubbed), on the test database. Used by Tests/test_threads.py for the restart (T5),
concurrency (T8) and no-shared-memory (T9) tests. Not a test module.

    python Tests/thread_app.py <port> <request log .jsonl> [delay_s]

The environment names the user (FPL_USER_ID), the database (DB_NAME) and the gate key (APP_API_KEY); tracing is off."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "squad"), str(HERE.parent / "eval"), str(HERE)]


def main():
    port, log_path = int(sys.argv[1]), sys.argv[2]
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
    os.environ["LANGFUSE_ENABLED"] = "0"
    import agent
    import main as app_main
    import thread_fakes as tf
    tf.stub_agent(agent, tf.Brain(log_path=log_path, delay=delay))
    import uvicorn
    uvicorn.run(app_main.app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
