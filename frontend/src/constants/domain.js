export const domain = {
  "id": "gb-0043",
  "direction": "关联分析",
  "title": "杉页阅读路径接续册",
  "slug": "reading-transition",
  "algorithm": "transition",
  "entities": "ReadingCollection / ReadingSession / TransitionRun / EditorialPlan",
  "scenario": "匿名章节阅读会话→路径接续关联→编辑衔接建议；仅会话内相邻，禁止跨会话拼接，非因果",
  "visual": "书页页边批注、墨蓝土黄",
  "oracle": "手算会话A-B-C与A-C；单项不产生边；基率分母定义明确",
  "frontend": 18247,
  "backend": 19247,
  "db_port": 17747,
  "database": "MySQL8",
  "batch": 1,
  "code": "SY",
  "source": "阅读文集",
  "record": "匿名阅读会话",
  "note": "编辑衔接建议",
  "source_table": "reading_collections",
  "record_table": "reading_sessions",
  "run_table": "transition_runs",
  "note_table": "editorial_plans",
  "eyebrow": "MARGIN NOTES / 43",
  "headline": "读者翻过这一页，接着去了哪里。",
  "subtitle": "杉页数字出版组 · 会话内章节接续研究",
  "fields": [
    [
      "session",
      "匿名会话编号",
      "text"
    ],
    [
      "path",
      "章节路径（用 > 分隔）",
      "text"
    ]
  ],
  "params": [
    [
      "min_count",
      "最少接续次数",
      3
    ],
    [
      "top_n",
      "保留接续规则数",
      20
    ]
  ],
  "sample": {
    "session": "SY-NEW-01",
    "path": "序章>材料>工艺>案例"
  },
  "seed_count": 240,
  "ink": "oklch(28% .04 250)",
  "accent": "oklch(60% .13 78)",
  "paper": "oklch(95% .022 85)",
  "principle": "只统计同一会话内的相邻章节；提升度相对于所有接续边的目标章节基率，关联不代表编辑调整造成的因果效果。",
  "default_parameters": {
    "min_count": 3,
    "top_n": 20
  },
  "method_label": "会话内一阶转移计数、条件概率与相对全局基率提升",
  "result_headline": "一条接续关系，三个明确的分母。",
  "column_labels": {
    "reference": "样本编号",
    "actual": "实际类型",
    "predicted": "预测类型",
    "posterior": "最高类后验",
    "cluster": "分区编号",
    "kind": "微站类型",
    "temperature": "温度 ℃",
    "humidity": "湿度 %",
    "particles": "颗粒浓度",
    "from": "当前章节",
    "to": "下一章节",
    "count": "接续次数",
    "conditional_probability": "条件概率",
    "target_base_rate": "目标章节基率",
    "lift": "提升度",
    "support": "边支持度",
    "actual_minutes": "实测时长 min",
    "predicted_minutes": "预测时长 min",
    "error_minutes": "预测误差 min",
    "visitor": "匿名访客",
    "exhibit": "展品编号",
    "prediction": "预计评分",
    "method": "计算依据",
    "neighbor_count": "参与邻居数"
  }
};
