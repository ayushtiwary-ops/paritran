"""F9 groundedness gate (SPEC 6.8, REAL gate over a real generative step).

Gate rule, unchanged from the prototype: a claim ``(section, quote)``
passes iff the section exists in the target corpus AND the quote is a
verbatim case-insensitive substring of that section's text. Catches both
paraphrase and invention.

Withheld claims are sub-classified:

- ``invented_section``: the cited section does not exist in the corpus,
- ``unverifiable_quote``: the section exists but the quote is not
  verbatim (includes honest paraphrase).

The headline metric is therefore labelled "ungrounded (withheld) claim
rate", never "hallucination rate": this gate is deliberately stricter
than hallucination detection and withholds accurate paraphrase too.

``leaked`` counts ground-truth fabrications (``is_fabricated is True``)
that PASSED the gate. It is recomputed here on every evaluation, never
asserted: a zero is a measurement, meaningful because the stub generator
plants known fabrications. Claims from live models carry
``is_fabricated=None`` and can never contribute to ``leaked``.
"""

from typing import Iterable

from paritran.engine.types import Claim, ClaimGenerator, ClaimVerdict, F9Result

__all__ = ["Gate"]


class Gate:
    """Verbatim-substring groundedness gate over one corpus version."""

    def __init__(self, corpus: dict[str, str], corpus_version: str):
        """``corpus`` maps section id to that section's text (v1: condensed
        descriptions; v2: bare-act verbatim text). ``corpus_version`` is
        carried on every result so no number ever detaches from the corpus
        it was measured against."""
        self.corpus = dict(corpus)
        self.corpus_version = corpus_version

    def check(self, section: str, quote: str) -> bool:
        """The prototype's gate rule, byte-exact semantics.

        ``sec in CORPUS and quote.strip().lower() in CORPUS[sec].lower()``.
        Note the prototype-inherited edge: an empty quote against an
        existing section passes vacuously. No generator in this codebase
        emits empty quotes (the stub never does; the Ollama parser drops
        them as malformed), and changing the rule would break byte-exact
        reproduction of the frozen baseline.
        """
        return (
            section in self.corpus
            and quote.strip().lower() in self.corpus[section].lower()
        )

    def evaluate(
        self,
        claims: Iterable[Claim],
        *,
        generator_name: str = "unlabelled",
        is_stub: bool = True,
    ) -> F9Result:
        """Gate every claim and return the full F9 result.

        ``generator_name`` and ``is_stub`` label the result for the UI.
        The defaults are the honest direction: an unlabelled evaluation
        presents as a stub, never as a live model run. Prefer
        :meth:`run`, which takes the labels from the generator itself.
        """
        verdicts: list[ClaimVerdict] = []
        passed = withheld = leaked = 0
        for claim in claims:
            if self.check(claim.section, claim.quote):
                verdicts.append(
                    ClaimVerdict(claim=claim, verdict="PASSED", sub_class=None)
                )
                passed += 1
                if claim.is_fabricated is True:
                    leaked += 1
            else:
                sub_class = (
                    "invented_section"
                    if claim.section not in self.corpus
                    else "unverifiable_quote"
                )
                verdicts.append(
                    ClaimVerdict(claim=claim, verdict="WITHHELD", sub_class=sub_class)
                )
                withheld += 1
        return F9Result(
            generator_name=generator_name,
            is_stub=is_stub,
            corpus_version=self.corpus_version,
            claims=len(verdicts),
            passed=passed,
            withheld=withheld,
            leaked=leaked,
            verdicts=verdicts,
        )

    def run(self, generator: ClaimGenerator, context: dict) -> F9Result:
        """Generate claims and gate them, labelled by the generator."""
        return self.evaluate(
            generator.generate_claims(context),
            generator_name=generator.name,
            is_stub=generator.is_stub,
        )
