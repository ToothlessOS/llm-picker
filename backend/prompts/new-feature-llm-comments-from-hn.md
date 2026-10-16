# New Feature to implement: Collect and visualization LLM related threads from HackerNews - so that our llm-picker provides more than benchmarks!

# Draft

## Data source

1. Official HN API: https://github.com/hackernews/api
2. HN Search API: https://hn.algolia.com/api

## Flow

1. Check the top HN threads and identify the threads related to LLMs through keyword search - a thread can look something like:

```text
Muse Spark Open (meta.ai)
646 points by bigwheels 8 hours ago | hide | past | favorite | 360 comments
	
https://dev.meta.ai/resources/blog/build-with-muse-spark-ope...

https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B

https://9to5mac.com/2026/10/15/meta-launches-new-muse-spark-...
```

2. Download and store the full threads in the backend (also preprocess to make them ready for visualization!)

3. The frontend get the list of threads from a new backend API endpoint

4. The frontend should visualize each thread as a discussion tree + plus a read panel for checking the details. It should support keyword search and filter by companies / service / provider.

5. Utilize the cron mechanism already implemented in the backend and refresh the threads each hour. Keep a bank for the threads - only keep recent ones (for example, posted within a week / 14 days) only keep the top 10 in these according to their up-votes / number of comments.