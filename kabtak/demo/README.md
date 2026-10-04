# Demo recording

`kabtak-local-demo.webm` is an automated 1280×720 screen recording of Kabtak
running locally. It opens the packaged historical replay, shows the student
deadline separately from other actors' deadlines, and displays the preserved
evidence receipt. The replay makes no SerpApi, Groq, or public-source request.

The script records only after both local servers are running:

```bash
# terminal 1
cd kabtak/backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# terminal 2
cd kabtak/frontend
pnpm dev

# terminal 3
cd kabtak/frontend
pnpm demo:record
```

The generated file replaces `kabtak/demo/kabtak-local-demo.webm`. Verify its
duration before uploading:

```bash
ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 \
  kabtak/demo/kabtak-local-demo.webm
```

For submission, a public repository link to the file is possible, but an unlisted
YouTube or shareable Google Drive link usually gives judges a better streaming
experience. Test the final URL in a private/incognito window without signing in.
