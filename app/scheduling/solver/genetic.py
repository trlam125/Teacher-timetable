"""Genetic candidate decoding and population search."""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import partial
from typing import Optional
import random

from sqlalchemy.orm import Session

from .context import SearchBudget, candidate_key, genes_from_candidate as _candidate_genes
from .problem import SchedulingProblem
from .scoring import _schedule_soft_score
from app.models import Project
from app.scheduling.rules import assignment_prefers_double


class GeneticSearch:
    def __init__(self, problem: SchedulingProblem):
        self.problem = problem
        self.candidate_by_start = [
            {row[0]: row for row in options} for options in problem.task_candidates
        ]

    def evaluate(self, genes: list[int | None]):
        """Honor inherited positions, then repair only unresolved placements."""
        task_rows = self.problem.task_rows
        existing = self.problem.existing
        assignment_by_id = self.problem.assignment_by_id
        ppd = self.problem.periods_per_day
        p = self.problem.project
        assignments = self.problem.assignments
        task_candidates = self.problem.task_candidates
        candidate_by_start = self.candidate_by_start

        teacher_busy = defaultdict(set)
        class_busy = defaultdict(set)
        assignment_busy = defaultdict(set)
        teacher_day = Counter()
        class_sub_day = Counter()
        class_sub_slots = defaultdict(set)
        placed = []
        chosen_starts = [None] * len(task_rows)

        for lesson in existing:
            assignment = assignment_by_id.get(lesson.assignment_id)
            if not assignment:
                continue
            day = lesson.slot // ppd
            teacher_busy[assignment.teacher_id].add(lesson.slot)
            class_busy[assignment.class_id].add(lesson.slot)
            assignment_busy[assignment.id].add(lesson.slot)
            teacher_day[(assignment.teacher_id, day)] += 1
            class_sub_day[(assignment.class_id, assignment.subject_id, day)] += 1
            class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
                lesson.slot % ppd
            )

        def feasible(index: int, row) -> bool:
            (
                assignment,
                _group_index,
                size,
                _explicit,
                _forced,
                anchor_slots,
                _planned,
            ) = task_rows[index]
            slot, _group_slots, new_slots, day, session, period = row
            missing_size = size - len(anchor_slots)
            if any(
                candidate in teacher_busy[assignment.teacher_id]
                or candidate in class_busy[assignment.class_id]
                for candidate in new_slots
            ):
                return False
            if (
                teacher_day[(assignment.teacher_id, day)] + missing_size
                > ppd
            ):
                return False
            existing_periods = [
                candidate % p.periods_per_session
                for candidate in class_sub_slots[
                    (assignment.class_id, assignment.subject_id, day)
                ]
                if candidate // p.periods_per_session == session
            ]
            run = sorted(set(existing_periods) | set(range(period, period + size)))
            longest = current = 1
            for left, right in zip(run, run[1:]):
                current = current + 1 if right == left + 1 else 1
                longest = max(longest, current)
            return longest <= max(
                1, int(p.periods_per_session)
            )

        def row_soft_score(index: int, row, gene: int | None) -> float:
            assignment, _group_index, size, _explicit, _forced, _anchor, _planned = (
                task_rows[index]
            )
            slot, _group_slots, new_slots, day, _session, period = row
            score = class_sub_day[
                (assignment.class_id, assignment.subject_id, day)
            ] * 8 + sum(
                (candidate % p.periods_per_session) * 0.15 for candidate in new_slots
            )
            neighbors = []
            if period > 0:
                neighbors.append(slot - 1)
            if period + size < p.periods_per_session:
                neighbors.append(slot + size)
            for neighbor in neighbors:
                if neighbor in teacher_busy[assignment.teacher_id]:
                    score -= 1.2
                if (
                    assignment_prefers_double(assignment)
                    and neighbor in assignment_busy[assignment.id]
                ):
                    score -= 7.0
            if gene is not None and slot != gene:
                # Repair should stay near the inherited gene when several
                # alternatives are otherwise similar, but this is only a
                # tiebreaking repair cost -- not the chromosome semantics.
                score += abs(slot - gene) * 0.12
            return score

        def place(index: int, row):
            assignment, _group_index, _size, _explicit, forced, _anchor, _planned = (
                task_rows[index]
            )
            slot, _group_slots, new_slots, day, _session, _period = row
            chosen_starts[index] = slot
            for candidate in new_slots:
                teacher_busy[assignment.teacher_id].add(candidate)
                class_busy[assignment.class_id].add(candidate)
                assignment_busy[assignment.id].add(candidate)
                class_sub_slots[(assignment.class_id, assignment.subject_id, day)].add(
                    candidate % ppd
                )
                placed.append(
                    (assignment.id, candidate, forced is not None, f"task:{index}")
                )
            teacher_day[(assignment.teacher_id, day)] += len(new_slots)
            class_sub_day[(assignment.class_id, assignment.subject_id, day)] += len(
                new_slots
            )

        pending = []
        for index, task in enumerate(task_rows):
            forced = task[4]
            gene = forced if forced is not None else genes[index]
            row = candidate_by_start[index].get(gene) if gene is not None else None
            if row is not None and feasible(index, row):
                place(index, row)
            else:
                pending.append(index)

        # Repair only the genes that could not be honored. Dynamic MRV reduces
        # the chance that a flexible repair steals the last slot from a hard one.
        unresolved = []
        pending = set(pending)
        options_by_task = {
            index: [row for row in task_candidates[index] if feasible(index, row)]
            for index in pending
        }
        pending_by_teacher = defaultdict(set)
        pending_by_class = defaultdict(set)
        for index in pending:
            owner = task_rows[index][0]
            pending_by_teacher[owner.teacher_id].add(index)
            pending_by_class[owner.class_id].add(index)
        while pending:
            selected_index = None
            selected_options = None
            for index in tuple(pending):
                options = options_by_task[index]
                if not options:
                    unresolved.append(index)
                    pending.remove(index)
                    continue
                if selected_options is None or len(options) < len(selected_options):
                    selected_index = index
                    selected_options = options
                    if len(options) == 1:
                        break
            if selected_index is None:
                continue
            pending.remove(selected_index)
            forced = task_rows[selected_index][4]
            gene = forced if forced is not None else genes[selected_index]
            best_row = min(
                selected_options,
                key=lambda row: (
                    row_soft_score(selected_index, row, gene),
                    row[0],
                ),
            )
            place(selected_index, best_row)
            owner = task_rows[selected_index][0]
            affected = pending_by_teacher[owner.teacher_id] | pending_by_class[owner.class_id]
            for index in affected & pending:
                options_by_task[index] = [row for row in options_by_task[index] if feasible(index, row)]

        unscheduled = sum(
            max(1, task_rows[index][2] - len(task_rows[index][5]))
            for index in unresolved
        )
        final_slots = defaultdict(set)
        for lesson in existing:
            final_slots[lesson.assignment_id].add(lesson.slot)
        for assignment_id, slot, _locked, _block_token in placed:
            final_slots[assignment_id].add(slot)
        score = unscheduled * 10000 + _schedule_soft_score(
            p, assignments, assignment_by_id, final_slots
        )
        return {
            "lessons": placed,
            "unscheduled": unscheduled,
            "score": round(score, 2),
            "genes": chosen_starts,
            "solver": "ga_fallback",
        }

    def random_gene(self, index: int, task):
        task_candidates = self.problem.task_candidates
        forced = task[4]
        if forced is not None:
            return forced
        pool = [row[0] for row in task_candidates[index]]
        return random.choice(pool) if pool else None

    def mutate(self, genes, mutation_rate: float = 0.16):
        task_rows = self.problem.task_rows
        random_gene = self.random_gene
        child = genes[:]
        for index, task in enumerate(task_rows):
            forced = task[4]
            if forced is not None:
                child[index] = forced
                continue
            if random.random() < mutation_rate:
                # Most mutations choose another real candidate. A small share
                # clears the gene and lets the repair decoder explore freely.
                child[index] = (
                    random_gene(index, task) if random.random() < 0.92 else None
                )
        return child

    def crossover(self, left, right):
        task_rows = self.problem.task_rows
        child = []
        for index, task in enumerate(task_rows):
            forced = task[4]
            if forced is not None:
                child.append(forced)
            else:
                child.append(left[index] if random.random() < 0.5 else right[index])
        return child

    def evolve(self, best_candidate, *, tries: int, budget: SearchBudget, alternate=None):
        """Improve the incumbent with bounded population search."""
        task_rows = self.problem.task_rows
        deadline_hit = budget.expired
        evaluate = self.evaluate
        random_gene = self.random_gene
        mutate = self.mutate
        crossover = self.crossover
        genes_from_candidate = partial(_candidate_genes, task_count=len(task_rows))
        population_size = max(24, min(48, max(24, len(task_rows) // 2 + 14)))
        generations = max(20, min(55, max(tries // 4, 24)))
        elite_count = max(3, population_size // 6)

        population = [genes_from_candidate(best_candidate)]
        if alternate is not None:
            cp_genes = genes_from_candidate(alternate)
            if cp_genes != population[0]:
                population.append(cp_genes)
        while len(population) < population_size:
            population.append(
                [random_gene(index, task) for index, task in enumerate(task_rows)]
            )

        def evaluate_population(items):
            result = []
            for genes in items:
                if result and deadline_hit(0.05):
                    break
                candidate = evaluate(genes)
                # Lamarckian repair: successful repaired placements become the
                # chromosome inherited by the next generation instead of throwing
                # that information away and keeping the pre-repair genotype.
                result.append((candidate, genes_from_candidate(candidate)))
            if not result:
                result.append((best_candidate, genes_from_candidate(best_candidate)))
            result.sort(key=lambda item: candidate_key(item[0]))
            return result

        def tournament_pick(evaluated, size: int = 4):
            sample_size = min(size, len(evaluated))
            contenders = random.sample(evaluated, sample_size)
            contenders.sort(key=lambda item: candidate_key(item[0]))
            return contenders[0][1]

        evaluated = evaluate_population(population)
        if candidate_key(evaluated[0][0]) < candidate_key(best_candidate):
            best_candidate = evaluated[0][0]

        stagnant_generations = 0
        for generation in range(generations):
            if deadline_hit(0.08):
                break
            previous_best = candidate_key(best_candidate)
            elites = [genes[:] for _candidate, genes in evaluated[:elite_count]]
            next_population = elites

            # Increase exploration after stagnation instead of repeatedly crossing
            # nearly identical elites. Random immigrants preserve search diversity.
            mutation_rate = min(0.34, 0.14 + stagnant_generations * 0.025)
            immigrant_rate = min(0.22, 0.08 + stagnant_generations * 0.02)
            seen = {tuple(genes) for genes in next_population}
            attempts = 0
            while len(next_population) < population_size:
                if deadline_hit(0.05):
                    break
                attempts += 1
                if random.random() < immigrant_rate:
                    child = [
                        random_gene(index, task) for index, task in enumerate(task_rows)
                    ]
                else:
                    parent1 = tournament_pick(evaluated)
                    parent2 = tournament_pick(evaluated)
                    child = mutate(
                        crossover(parent1, parent2),
                        mutation_rate=mutation_rate,
                    )
                key = tuple(child)
                # Avoid a population collapse, but never loop forever if the search
                # space itself is tiny.
                if key in seen and attempts < population_size * 8:
                    continue
                seen.add(key)
                next_population.append(child)

            evaluated = evaluate_population(next_population)
            if candidate_key(evaluated[0][0]) < candidate_key(best_candidate):
                best_candidate = evaluated[0][0]

            if candidate_key(best_candidate) < previous_best:
                stagnant_generations = 0
            else:
                stagnant_generations += 1

            # Once a complete solution exists, a few additional generations can
            # improve soft quality; no need to spend the whole fallback budget.
            if (
                best_candidate["unscheduled"] == 0
                and generation >= 8
                and stagnant_generations >= 6
            ):
                break

        return best_candidate


def ga_schedule(
    db: Session, p: Project, mode: str, tries: int = 120,
    target_assignment_ids: Optional[set[int]] = None, deadline: float | None = None,
):
    """Compatibility entry point; request orchestration lives in engine.py."""
    from .engine import ga_schedule as run
    return run(db, p, mode, tries, target_assignment_ids, deadline)


__all__ = [
    'GeneticSearch', 'ga_schedule',
]
