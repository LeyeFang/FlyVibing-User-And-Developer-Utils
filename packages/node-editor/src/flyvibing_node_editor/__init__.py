"""
NodeEditor — 节点图 agent 通道与工具。

  mcp_server      — MCP 4 工具（get_rules 分节 / get_scene_entities / build_graph / apply_graph）
  cli             — 终端通道（python -m flyvibing_node_editor.cli rules|entities|build|apply）
  rule_sections   — rules.md 分节读取（渐进披露）
  spec_builder    — 实验 spec → 节点图 JSON（build_graph 实现）
  graph_builder   — 程序化构图器（GraphBuilder）
  node_graph_validator — 校验唯一实现（L1 规则 + CLI；引擎内 validation 调用它）
  graph_flow          — 静态执行流分析（V1: 不执行引擎，回答“这么连会什么顺序”）
"""
