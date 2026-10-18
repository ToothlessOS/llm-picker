# LLM Picker: Final Report

## Introduction

Nowadays, LLMs are an integral part of in our work - we use them for coding, research, summarize documents and emails, and many other different tasks. However, there are so many different options out there, and selecting the LLM that fits our tasks the best is no longer simply selecting the highest benchmark score. **Capability against price**, **latency**, **task specialization** and **reviews from real users** all need to be considered - which can be painstaking process.

Our project, **LLM Picker**, is motivated by making this decision process easier for students, developers, researchers, and other LLM users who need to choose a model for a particular task and budget. We build a visualization dashboard that presents both subjective benchmarks (performance, task fit, cost & speed) and objective user reviews (based on Hacker News threads). Our visualization gives a clear view of the metrics above to support comparison and informed choice of LLMs.

## Method

### Data Sources

- Benchmarks from established sources:
    1. [Artificial Analysis (AA) via API](https://artificialanalysis.ai/api) for model metadata, Intelligence, Coding and Agentic indices, cost per Intelligence Index task, token prices, median output speed, and time to first token.
    2. [LMArena via HuggingFace dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset) for agent, document, search, and web-development tasks.

    AA is based on objective tests while LMArena focuses more on subjective user experience (as it is based on rankings by test users). We combine the two to better indicate the overall performance of LLMs in the field.
    
- Objective user reviews of [HackerNews](https://news.ycombinator.com/news), online tech discussion forum by YCombinator. We used [this API](https://hn.algolia.com/api) for access. Although these threads cannot be converted into scores directly, they serves two important purposes: Firstly, they include news and discussions about recent releases / progress in LLMs. Secondly, they allow users to find what online users with similar demands and budget choose. Both add information beyond benchmark scores, which are important references for picking an LLM.

The `Django REST Framework` backend has a crontab (via Celery + Redis) and periodically requests data from the three sources to ensure data freshness (twice a day for LMArena and AA; Hourly for HackerNews).

After obtaining the data, we do the preprocessing - we join the AA entries and LMArena entries to create a joint dataset for visualization. This is the hard step - since the data ids and structures and IDs are different, we need to carefully build the fuzzy matching rules. For HackerNews, we only keep the threads related to LLM with keyword filtering.

The visualization frontend reads the visualization ready data from the backend's API endpoints.

### Stacks

The frontend uses TypeScript, React 19, D3 7, SVG, React Query, React Router, HTML, and responsive CSS, built with Vite. D3 implements scales, axes, marks, brushing, and pointer interactions; React owns application and linked-view state. The backend uses Python/Django, with validation, provenance metadata, freshness reporting, and automated tests. Day and night themes use the same semantics with contrast-adjusted colors.

## Results

### 1. Performance Explorer

![Performance Explorer with scatterplot, Pareto front, parallel coordinates, and rank comparison](assets/final-report/performance-explorer.png)

This coordinated view answers “Which model is worth the price?” and “Which model is both fast and capable?” Users switch between cost and speed, choose Intelligence/Coding/Agent performance, select cost or speed measures, filter providers, and change between log and linear cost scales. The scatterplot encodes cost or speed on *x*, performance on *y*, provider by color, a dashed Pareto front, and a median-based attractive region. Users can pin up to three models, brush a region, or brush ranges on parallel axes; linked marks and the model list update together. A rank-comparison chart shows how pinned models change position across the three performance measures.

In the example of the screenshot - several inexpensive models remain Pareto-efficient while the higher-scoring models are not automatically the best-value choices. With this, users can choose the best performing model within their budgets. Or if they need fast models - it helps them find the sweet point between speed and performance.

Another interesting design is the coordinated interactions with the pinned models - the comparison table shows the raw stats of the pinned models side-by-side, while the Parallel coordinates allow the different performance facets to be visualized. This gives users a more comprehensive view of the results.

### 2. Cost per Task

![Stacked bars showing cost per Intelligence Index task](assets/final-report/cost-per-task.png)

This sorted stacked bar chart explains the monetary side details of the decision. Bar height is AA's estimated USD cost per Intelligence Index task; segments show the proportional mix of input, output, cache-write, and cache-hit list prices. Hovering reveals values, clicking opens a model page, and legend clicks isolate a component. The median reference line makes comparison immediate. Current costs range from about $0.05 to $7.83 per task, with a median near $1.09. MiMo-V2.5-Pro, MiMo-V2.6-Flash, and GPT-6 Luna are among the cheapest, while several top-end models cost many times the median. This visualization allow user to easily filter out models that exceed their budget limits.

### 3. Task Fit

![Task Fit heatmap of LMArena category ranks](assets/final-report/task-fit.png)

The heatmap asks which model fits a specific job. Rows are matched models, columns are Agent, Document, Search, and WebDev, cell labels are ranks, and darker teal means a stronger rank within that column. Users click a task heading or legend control to sort, hover for the raw score/rating and rank, and click a row to open its model card. Empty cells mean “not evaluated,” not zero. LMArena has complete Agent coverage (42/42) and broad WebDev coverage (37/42), but sparse Document (10/42) and Search (6/42) coverage - a limitation of the data source.

Comparing the Agent and the WebDev entries, a practical finding is that GPT-6.1 Sol (Max) loses to GPT-6 Astra (Max) on Agent but wins on WebDev - so if you are using your OpenAI subscription of WebDev, using GPT-6.1 Sol is the option. It saves credits and gives a better result.

### 4. Model Card

![Five-axis percentile model card](assets/final-report/model-card.png)

The radar chart summarizes one model across Intelligence, Coding, Agentic, Cost, and Speed. Every axis is a percentile among models measured on that attribute; the dashed polygon is the cohort median, and cost is inverted so farther outward means cheaper. Users choose a model from the list, hover another for comparison, inspect an axis, and follow a link to detailed records. Missing axes remain gaps rather than false zeros.

The radar chart is useful if the user wants to pick a balanced model in terms of cost, soeed and performance - the GLM-5.3 (Max) shown here is a good example.

### 5. Discussion Map

![Discussion Map for the Mistral Large 4 Hacker News thread](assets/final-report/discussion-map.png)

HackerNews is a great source for LLM-related discussions, however, the original page uses an old-school forum layout, making it hard to navigate. Therefore, we implement the discussion map visualization following [the ConVis paper](https://onlinelibrary.wiley.com/doi/full/10.1111/cgf.12378).

It preserves the tree structure of the original thread and comments. Additionally, it encodes mentioning of LLM service / provider in each thread. Each block is a comment; horizontal indentation represents reply depth, height represents text length with a cap, and colored bands identify mentioned providers or services. Users select a thread, search comment text, add provider/service filters, choose visible depth, hide unmatched branches, expand compacted subtrees, and click a block to read that branch. The map and reader stay synchronized as reading progresses.

We aim to make it easier for users to go through the HackerNews discussions to learn about the latest progress with LLMs and identify posts that help them find what online users with similar demands and budget choose - important references besides AA and LMArena benchmark scores. For example, this screenshot shows user sharing cheap Google AI pro plans with Verizon subscription - great tips for saving money.

## Discussion

### What data and attributes are represented?

Quantitative attributes (indices, prices, latency, throughput, ranks), categorical attributes (provider, task, entity), and hierarchical text (comment trees)

### What user tasks or goals does the visualization support?

Comparison, filtering (for different facets of performance, cost and speed) trade-off analysis (the Pareto front in the Performance Explorer), profile lookup (the Model Card), and exploration of discussions in the community (the Discussion Map).

### What visual idioms, marks, channels, and interactions are used?

Scatterplots and Pareto lines for two-objective optimization; parallel coordinates for conjunctive multivariable filtering; a bump-style rank chart for relative order; stacked bars for part-to-whole cost explanation; a heatmap for model-by-task scanning; a radar chart for one-model profiling; and indented blocks for discussion structure with color encoding for semantics / topics.

Our strongest design feature is coordination. Pinning, hover, brushing, filtering, and persistent selections let users move from overview to candidates to detail without losing context. Explicit notes prevent common errors: ranks are not score gaps, log axes omit nonpositive values, task cost is not a personal chat bill, and missing measurements are not zeros. The responsive themes and direct labels also improve accessibility.

Two main limitations remain - first, the insufficient coverage of the dataset used - the missing data / dimensions in the Task Fit and the Model Card. Also, the existing benchmarks are heavily based on agentic and coding skills, which do not include some other common tasks that one may use LLMs for (i.e. Writing, education, healthcare ...). For the next step, we can try to include more of these domain specific benchmarks. One good source is [vals.ai](https://www.vals.ai/home), where they provide a industry leaderboard that include benchmarks for 10 real-world industries.

Secondly, visualization and interaction can be further improved. Future tasks include: add historical trends, uncertainty intervals, user-defined workload/token assumptions, clearer color-accessible palettes, and a transparent recommendation panel that preserves rather than hides the underlying trade-offs.

## Conclusion

LLM picker takes benchmark scores, speed, cost, task fit by user voting and real-world user reviews and builds a visualization dashboard for a relatively comprehensive comparsion of different LLMs and showcases the tradeoffs. Our project turns scattered measurements and large bodies of discussions into explorable knowledge on LLMs for decision making. Its contribution is not a single “best model,” but a way for users to identify which evidence matters for their own workload and make a decision whose trade-offs are visible.

## Roles and Responsibilities

- **Siyuan Cao:** data acquisition; backend APIs, refresh/matching infrastructure, deployment, and testing; interface/web development.
- **Ziyue Zhang:** data cleaning and processing; D3 visualization implementation; interaction design, theming, homepage refinement, and the cost/speed performance views.
- **Haoyuan Zheng:** typed frontend API and application-state foundations; interface components, data states, documentation, and presentation/interim materials.
- **All team members:** research questions, analysis, visualization and interaction design reviews, testing feedback, and final presentation preparation.

