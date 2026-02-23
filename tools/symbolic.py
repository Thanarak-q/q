"""Symbolic verification tool for formal binary analysis.

Wraps angr, z3, checksec, and ropper — all dependencies are lazy-imported
so the tool loads instantly and gracefully reports when deps are missing.
"""
from __future__ import annotations

import ast
import subprocess
import textwrap
from typing import Any

from tools.base import BaseTool, ToolParameter

MAX_OUTPUT = 6000


class SymbolicTool(BaseTool):
    """Formal binary analysis using symbolic execution and constraint solving."""

    name = "symbolic"
    description = (
        "Formal binary analysis: checksec (protections), ropper (ROP gadgets), "
        "angr (symbolic execution), z3 (constraint solving). "
        "All deps optional — install only what you need."
    )
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Analysis action to perform",
            required=True,
            enum=["checksec", "ropper_gadgets", "angr_analyze", "z3_solve"],
        ),
        ToolParameter(
            name="binary",
            type="string",
            description="Path to binary file (for checksec, ropper_gadgets, angr_analyze)",
            required=False,
        ),
        ToolParameter(
            name="target",
            type="string",
            description="Target address/symbol for angr, or search pattern for ropper (e.g. 'pop rdi')",
            required=False,
        ),
        ToolParameter(
            name="avoid",
            type="string",
            description="Comma-separated addresses to avoid in angr (e.g. '0x401050,0x401060')",
            required=False,
        ),
        ToolParameter(
            name="constraints",
            type="string",
            description="Python-style constraints for z3 (e.g. 'x + y == 10, x > 0, y > 0')",
            required=False,
        ),
    ]

    def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action", "")
        if action == "checksec":
            return self._checksec(kwargs.get("binary", ""))
        elif action == "ropper_gadgets":
            return self._ropper_gadgets(kwargs.get("binary", ""), kwargs.get("target", ""))
        elif action == "angr_analyze":
            return self._angr_analyze(
                kwargs.get("binary", ""),
                kwargs.get("target", ""),
                kwargs.get("avoid", ""),
            )
        elif action == "z3_solve":
            return self._z3_solve(kwargs.get("constraints", ""))
        else:
            return f"Unknown action: {action}. Use: checksec, ropper_gadgets, angr_analyze, z3_solve"

    def _checksec(self, binary: str) -> str:
        """Check binary security protections."""
        if not binary:
            return "Error: 'binary' parameter required for checksec"

        # Try checksec CLI first
        try:
            result = subprocess.run(
                ["checksec", "--file", binary],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()[:MAX_OUTPUT]
        except FileNotFoundError:
            pass
        except Exception:
            pass

        # Fallback to pwntools ELF
        try:
            from pwn import ELF
            elf = ELF(binary, checksec=False)
            checks = {
                "RELRO": elf.relro or "No RELRO",
                "Stack Canary": "Canary found" if elf.canary else "No canary",
                "NX": "NX enabled" if elf.nx else "NX disabled",
                "PIE": "PIE enabled" if elf.pie else "No PIE",
                "Arch": elf.arch,
                "Bits": str(elf.bits),
            }
            lines = [f"checksec: {binary}"]
            for key, val in checks.items():
                lines.append(f"  {key}: {val}")
            return "\n".join(lines)
        except ImportError:
            return (
                "checksec requires either:\n"
                "  1. checksec CLI: apt install checksec\n"
                "  2. pwntools: pip install pwntools\n"
                "Neither is available."
            )
        except Exception as exc:
            return f"checksec error: {exc}"

    def _ropper_gadgets(self, binary: str, target: str) -> str:
        """Find ROP gadgets using ropper."""
        if not binary:
            return "Error: 'binary' parameter required for ropper_gadgets"

        try:
            from ropper import RopperService
        except ImportError:
            return (
                "ropper not installed. Install with:\n"
                "  pip install ropper\n"
                "Or use shell tool: ropper --file <binary> --search 'pop rdi'"
            )

        try:
            rs = RopperService()
            rs.addFile(binary)
            rs.loadGadgetsFor()

            if target:
                gadgets = rs.search(search=target)
            else:
                gadgets = rs.getFileFor(name=binary).gadgets

            if not gadgets:
                return f"No gadgets found{' matching: ' + target if target else ''}"

            lines = [f"ROP Gadgets for {binary}" + (f" (filter: {target})" if target else "")]
            cap = 50
            for i, gadget in enumerate(gadgets[:cap]):
                lines.append(f"  {gadget}")

            if len(gadgets) > cap:
                lines.append(f"  ... ({len(gadgets) - cap} more, showing first {cap})")

            output = "\n".join(lines)
            return output[:MAX_OUTPUT]

        except Exception as exc:
            return f"ropper error: {exc}"

    def _angr_analyze(self, binary: str, target: str, avoid: str) -> str:
        """Symbolic execution with angr."""
        if not binary:
            return "Error: 'binary' parameter required for angr_analyze"

        try:
            import angr
            import claripy
        except ImportError:
            return (
                "angr not installed. Install with:\n"
                "  pip install angr\n"
                "Note: angr is ~500MB and may take a while to install."
            )

        try:
            proj = angr.Project(binary, auto_load_libs=False)
            state = proj.factory.entry_state()
            simgr = proj.factory.simulation_manager(state)

            # Parse target address
            find_addr = None
            if target:
                try:
                    if target.startswith("0x"):
                        find_addr = int(target, 16)
                    elif target.isdigit():
                        find_addr = int(target)
                    else:
                        # Try as symbol name
                        sym = proj.loader.find_symbol(target)
                        if sym:
                            find_addr = sym.rebased_addr
                        else:
                            return f"Symbol '{target}' not found in binary"
                except ValueError:
                    return f"Invalid target address: {target}"

            if find_addr is None:
                return "Error: 'target' parameter required for angr_analyze (address like 0x401234 or symbol name)"

            # Parse avoid addresses
            avoid_addrs = []
            if avoid:
                for addr_str in avoid.split(","):
                    addr_str = addr_str.strip()
                    try:
                        if addr_str.startswith("0x"):
                            avoid_addrs.append(int(addr_str, 16))
                        elif addr_str.isdigit():
                            avoid_addrs.append(int(addr_str))
                    except ValueError:
                        pass

            # Run with timeout
            simgr.explore(
                find=find_addr,
                avoid=avoid_addrs if avoid_addrs else None,
                timeout=60,
            )

            if simgr.found:
                found_state = simgr.found[0]
                lines = [f"angr: Path found to {hex(find_addr)}!"]

                # Try to get stdin input
                try:
                    stdin_data = found_state.posix.dumps(0)
                    if stdin_data:
                        lines.append(f"  Input (bytes): {stdin_data!r}")
                        # Try to show as string if printable
                        try:
                            decoded = stdin_data.decode("ascii", errors="replace")
                            lines.append(f"  Input (ascii): {decoded}")
                        except Exception:
                            pass
                except Exception:
                    pass

                # Constraint count
                try:
                    n_constraints = len(found_state.solver.constraints)
                    lines.append(f"  Constraints: {n_constraints}")
                except Exception:
                    pass

                lines.append(f"  States explored: {simgr.completion}")

                output = "\n".join(lines)
                return output[:MAX_OUTPUT]
            else:
                explored = len(simgr.deadended) + len(simgr.active)
                return (
                    f"angr: No path found to {hex(find_addr)} "
                    f"(explored {explored} states, "
                    f"deadended={len(simgr.deadended)}, "
                    f"active={len(simgr.active)})"
                )

        except Exception as exc:
            return f"angr error: {type(exc).__name__}: {exc}"

    def _z3_solve(self, constraints: str) -> str:
        """Solve constraints using z3 via safe AST parsing."""
        if not constraints:
            return "Error: 'constraints' parameter required for z3_solve"

        try:
            import z3
        except ImportError:
            return (
                "z3-solver not installed. Install with:\n"
                "  pip install z3-solver"
            )

        try:
            # Parse constraints safely using ast (NO eval)
            solver = z3.Solver()
            variables: dict[str, z3.ArithRef] = {}

            for constraint_str in constraints.split(","):
                constraint_str = constraint_str.strip()
                if not constraint_str:
                    continue

                expr = self._parse_z3_constraint(constraint_str, variables, z3)
                if expr is not None:
                    solver.add(expr)
                else:
                    return f"Failed to parse constraint: {constraint_str}"

            result = solver.check()
            if result == z3.sat:
                model = solver.model()
                lines = ["z3: SAT (satisfiable)"]
                lines.append("  Solution:")
                for name, var in sorted(variables.items()):
                    val = model.evaluate(var)
                    lines.append(f"    {name} = {val}")
                return "\n".join(lines)
            elif result == z3.unsat:
                return "z3: UNSAT (no solution exists for these constraints)"
            else:
                return "z3: UNKNOWN (solver could not determine satisfiability)"

        except Exception as exc:
            return f"z3 error: {type(exc).__name__}: {exc}"

    @staticmethod
    def _parse_z3_constraint(
        expr_str: str,
        variables: dict,
        z3_module: Any,
    ) -> Any:
        """Parse a Python-style constraint into a z3 expression using AST.

        Supports: ==, !=, <, >, <=, >=, +, -, *, //, %, &, |, ^
        Variables are auto-created as z3.Int on first use.
        """
        try:
            tree = ast.parse(expr_str, mode="eval")
        except SyntaxError:
            return None

        def _eval_node(node: ast.AST) -> Any:
            if isinstance(node, ast.Expression):
                return _eval_node(node.body)
            elif isinstance(node, ast.Compare):
                left = _eval_node(node.left)
                # Support chained comparisons: a < b < c
                result = None
                prev = left
                for op, comparator in zip(node.ops, node.comparators):
                    right = _eval_node(comparator)
                    cmp = _compare(prev, op, right)
                    if cmp is None:
                        return None
                    result = cmp if result is None else z3_module.And(result, cmp)
                    prev = right
                return result
            elif isinstance(node, ast.BinOp):
                left = _eval_node(node.left)
                right = _eval_node(node.right)
                return _binop(left, node.op, right)
            elif isinstance(node, ast.UnaryOp):
                operand = _eval_node(node.operand)
                if isinstance(node.op, ast.USub):
                    return -operand
                return None
            elif isinstance(node, ast.Name):
                name = node.id
                if name not in variables:
                    variables[name] = z3_module.Int(name)
                return variables[name]
            elif isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.Num):  # Python 3.7 compat
                return node.n
            return None

        def _compare(left: Any, op: ast.cmpop, right: Any) -> Any:
            if isinstance(op, ast.Eq):
                return left == right
            elif isinstance(op, ast.NotEq):
                return left != right
            elif isinstance(op, ast.Lt):
                return left < right
            elif isinstance(op, ast.Gt):
                return left > right
            elif isinstance(op, ast.LtE):
                return left <= right
            elif isinstance(op, ast.GtE):
                return left >= right
            return None

        def _binop(left: Any, op: ast.operator, right: Any) -> Any:
            if isinstance(op, ast.Add):
                return left + right
            elif isinstance(op, ast.Sub):
                return left - right
            elif isinstance(op, ast.Mult):
                return left * right
            elif isinstance(op, ast.FloorDiv):
                return left / right  # z3 integer division
            elif isinstance(op, ast.Mod):
                return left % right
            elif isinstance(op, ast.BitAnd):
                return left & right
            elif isinstance(op, ast.BitOr):
                return left | right
            elif isinstance(op, ast.BitXor):
                return left ^ right
            return None

        return _eval_node(tree)
