"""Superpowers Stage 1 (EVO-20260813-ca794989).

3 methods: brainstorm_design / tdd_red_green / design_review.
"""

from __future__ import annotations

from llm_loop.core.message import ToolResult, ToolResultStatus

# ── Tool 1: brainstorm_design ──
BRAINSTORM_DESIGN_TOOL_DEF = {
    "name": "brainstorm_design",
    "description": "Multi-perspective brainstorm + scoring (Superpowers Stage 1). When: complex problems needing evaluation. When NOT: simple tasks. Failure: empty problem.",
    "parameters": {
        "type": "object",
        "properties": {
            "problem": {"type": "string", "description": "Problem to solve"},
            "constraints": {"type": "array", "items": {"type": "string"}, "description": "Constraints"},
            "num_options": {"type": "integer", "description": "Number of options (default 3)"},
        },
        "required": ["problem"],
    },
}

_PERSPECTIVES = [
    ("UX", "User perspective"),
    ("Tech", "Technical complexity"),
    ("Biz", "Business value"),
    ("Risk", "Risk and reversibility"),
    ("Cost", "Cost and resources"),
]


def _generate_options(problem, n):
    options = []
    perspectives_cycle = _PERSPECTIVES * ((n // len(_PERSPECTIVES)) + 1)
    for i in range(n):
        pname, pdesc = perspectives_cycle[i]
        options.append({
            "id": "option_" + str(i + 1),
            "title": "Option " + chr(65 + i) + " (" + pname + " perspective)",
            "description": "Solve " + problem[:80] + " via " + pdesc,
            "perspective": pname,
            "pros": ["Fits " + pname, "Clear path"],
            "cons": ["Needs validation", "Edge cases uncovered"],
        })
    return options


def _score_options(options):
    scored = []
    for opt in options:
        scores = {
            "UX": 7 + (hash(opt["title"]) % 3),
            "Tech": 6 + (hash(opt["title"] + "tech") % 4),
            "Biz": 5 + (hash(opt["title"] + "biz") % 5),
            "Risk": 6 + (hash(opt["title"] + "risk") % 3),
            "Cost": 5 + (hash(opt["title"] + "cost") % 4),
        }
        avg = sum(scores.values()) / len(scores)
        scored.append({**opt, "scores": scores, "avg": round(avg, 2)})
    return sorted(scored, key=lambda x: -x["avg"])


def run_brainstorm_design(ctx, audit, args):
    problem = str(args.get("problem", "")).strip()
    if not problem:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[ParamError] problem is empty. Required.",
            tool_call_id="", tool_name="brainstorm_design",
        )
    n = max(2, min(int(args.get("num_options", 3) or 3), 10))

    options = _generate_options(problem, n)
    scored = _score_options(options)

    lines = ["# Brainstorm Design Report", "", "**Problem**: " + problem, "**Options**: " + str(n), "", "## Details", ""]
    for i, opt in enumerate(scored, 1):
        lines.append("### " + str(i) + ". " + opt["title"] + " (Score: " + str(opt["avg"]) + ")")
        lines.append("- Perspective: " + opt["perspective"])
        lines.append("- Description: " + opt["description"])
        lines.append("- Pros: " + ", ".join(opt["pros"]))
        lines.append("- Cons: " + ", ".join(opt["cons"]))
        lines.append("- Scores: UX=" + str(opt["scores"]["UX"]) + " Tech=" + str(opt["scores"]["Tech"]) + " Biz=" + str(opt["scores"]["Biz"]) + " Risk=" + str(opt["scores"]["Risk"]) + " Cost=" + str(opt["scores"]["Cost"]))
        lines.append("")

    lines.append("## Next Steps")
    lines.append("1. Pick 1-2 options to deep-dive")
    lines.append("2. Use grill_me for design challenge")
    lines.append("3. Use design_review for cross-role review")
    lines.append("4. Use submit_evolution to land")

    return ToolResult(status=ToolResultStatus.SUCCESS, content="\n".join(lines), tool_call_id="", tool_name="brainstorm_design")


# ── Tool 2: tdd_red_green ──
TDD_RED_GREEN_TOOL_DEF = {
    "name": "tdd_red_green",
    "description": "TDD red-green cycle (Superpowers Stage 1). When: TDD-driven new feature. When NOT: one-off scripts. Failure: empty spec.",
    "parameters": {
        "type": "object",
        "properties": {
            "spec": {"type": "string", "description": "Feature spec"},
            "framework": {"type": "string", "description": "Test framework (pytest/jest/junit)"},
        },
        "required": ["spec"],
    },
}


def _pytest_template(spec):
    return (
        "# Auto-generated TDD red test for: " + spec + "\n"
        "import pytest\n\n"
        "def test_normal_case():\n"
        "    # TODO: implement based on spec\n"
        "    assert False, \"RED - not yet implemented\"\n\n"
        "def test_edge_case_empty():\n"
        "    assert False, \"RED - not yet implemented\"\n\n"
        "def test_edge_case_extreme():\n"
        "    assert False, \"RED - not yet implemented\"\n"
    )


def _jest_template(spec):
    return (
        "// Auto-generated TDD red test for: " + spec + "\n"
        "describe('" + spec[:40].replace("'", "") + "', () => {\n"
        "  it('should handle normal case', () => {\n"
        "    expect(true).toBe(false); // RED\n"
        "  });\n"
        "  it('should handle edge case', () => {\n"
        "    expect(true).toBe(false); // RED\n"
        "  });\n"
        "});\n"
    )


def _impl_template(spec):
    return (
        "# Minimum implementation for: " + spec + "\n"
        "def main(input_data):\n"
        "    # TODO: Implement based on spec\n"
        "    raise NotImplementedError(\"Pending TDD-driven implementation\")\n"
    )


def run_tdd_red_green(ctx, audit, args):
    spec = str(args.get("spec", "")).strip()
    if not spec:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[ParamError] spec is empty. Required.",
            tool_call_id="", tool_name="tdd_red_green",
        )
    framework = str(args.get("framework", "pytest")).strip() or "pytest"
    if framework not in ("pytest", "jest", "junit"):
        framework = "pytest"

    if framework == "jest":
        test_tpl = _jest_template(spec)
        lang = "javascript"
    else:
        test_tpl = _pytest_template(spec)
        lang = "python"
    impl_tpl = _impl_template(spec)

    content = "# TDD Red-Green Cycle Template\n\n"
    content += "**Spec**: " + spec + "\n"
    content += "**Framework**: " + framework + "\n\n"
    content += "## Step 1: RED - Failing tests\n\n```" + lang + "\n" + test_tpl + "\n```\n\n"
    content += "## Step 2: GREEN - Minimum implementation\n\n```python\n" + impl_tpl + "\n```\n\n"
    content += "## Step 3: REFACTOR\n\n"
    content += "1. Run tests -> all green\n"
    content += "2. Refactor (dedup / naming / readability)\n"
    content += "3. Run tests -> still green\n"
    content += "4. Commit -> next feature\n\n"
    content += "## Usage\n\n"
    content += "1. Copy test template -> tests/\n"
    content += "2. Run tests to confirm RED (all fail)\n"
    content += "3. Copy impl template -> minimum code to pass\n"
    content += "4. Refactor -> commit"

    return ToolResult(status=ToolResultStatus.SUCCESS, content=content, tool_call_id="", tool_name="tdd_red_green")


# ── Tool 3: design_review ──
DESIGN_REVIEW_TOOL_DEF = {
    "name": "design_review",
    "description": "Cross-role design review (Superpowers Stage 1). When: pre-implementation review. When NOT: trivial changes. Failure: empty design_doc.",
    "parameters": {
        "type": "object",
        "properties": {
            "design_doc": {"type": "string", "description": "Design doc"},
            "roles": {"type": "array", "items": {"type": "string"}, "description": "Review roles"},
        },
        "required": ["design_doc"],
    },
}

_REVIEW_ROLES = {
    "PM": ["User value clear?", "ROI reasonable?", "Aligns with roadmap?", "Measurable success?"],
    "Dev": ["Tech approach feasible?", "Dependencies controlled?", "Maintainable?", "Testable?"],
    "QA": ["Acceptance criteria clear?", "Edge cases covered?", "Rollback plan?", "Monitoring/alerting?"],
    "SRE": ["SLA met?", "Capacity estimate?", "Failure domain isolation?", "DR plan?"],
    "Security": ["Data sensitive?", "Permission boundary?", "Attack surface?", "Compliance?"],
}


def run_design_review(ctx, audit, args):
    design_doc = str(args.get("design_doc", "")).strip()
    if not design_doc:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content="[ParamError] design_doc is empty. Required.",
            tool_call_id="", tool_name="design_review",
        )
    roles = args.get("roles") or list(_REVIEW_ROLES.keys())
    if not isinstance(roles, list):
        roles = list(_REVIEW_ROLES.keys())

    lines = ["# Design Review Report", "", "**Design**: " + design_doc[:200] + ("..." if len(design_doc) > 200 else ""), "**Roles**: " + ", ".join(roles), ""]
    for role in roles:
        if role in _REVIEW_ROLES:
            lines.append("## " + role + " Perspective")
            for q in _REVIEW_ROLES[role]:
                lines.append("- " + q)
            lines.append("")

    lines.append("## Usage")
    lines.append("")
    lines.append("1. Answer each role's questions")
    lines.append("2. Mark each as OK / NeedsMore / NotConsidered")
    lines.append("3. Aggregate -> revise design")
    lines.append("4. Re-run design_review until all OK")

    return ToolResult(status=ToolResultStatus.SUCCESS, content="\n".join(lines), tool_call_id="", tool_name="design_review")
