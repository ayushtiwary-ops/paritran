"""Deterministic fabricating stub generator (SPEC 6.8, STUB, labelled).

This is the prototype's ``mock_generate`` promoted behind the
:class:`~paritran.engine.types.ClaimGenerator` protocol, byte-exact:

- 50 claims total, cycling through the five real phrases below,
- every i with ``i % 5 == 0`` is a ground-truth-labelled fabrication,
- of those, ``i % 10 == 0`` invents the nonexistent section "BNS 420"
  (5 claims) and the rest are plausible paraphrases against a real
  section (5 claims),
- the remaining 40 claims quote corpus v1 verbatim.

Gated against corpus v1 this yields the frozen baseline
claims/passed/withheld/leaked = 50/40/10/0 (results.json, SPEC 6.1).
The stub fabricates on purpose so the F9 gate is exercised
non-tautologically even with no model running. It is always labelled:
``is_stub`` is True and the UI shows ``name`` next to every F9 number.
"""

from paritran.engine.types import Claim

__all__ = ["StubGenerator", "REAL_PHRASES"]

# Byte-identical to the prototype's `real` dict (src/paritran_prototype.py,
# mock_generate). Each value is a verbatim substring of the corpus v1 text
# for its section. Insertion order matters: the claim cycle is list(REAL_PHRASES).
REAL_PHRASES: dict[str, str] = {
    "BNS 318": "dishonestly inducing delivery of property",
    "BNS 319": "pretending to be some other person",
    "IT Act 66C": "unique identification feature",
    "IT Act 66D": "using any communication device or computer resource",
    "BNS 111": "continuing unlawful activity by a crime syndicate",
}


class StubGenerator:
    """The prototype's fabricating mock, deterministic and honest about it."""

    name: str = "deterministic-stub"
    is_stub: bool = True

    def generate_claims(self, context: dict) -> list[Claim]:
        """Return the prototype's exact 50-claim sequence.

        ``context`` is accepted for protocol compatibility and ignored:
        the stub is deterministic by design (the frozen baseline must
        not move with case content). ``is_fabricated`` carries the
        ground-truth label: True exactly when ``i % 5 == 0``.
        """
        secs = list(REAL_PHRASES)
        out: list[Claim] = []
        for i in range(50):
            sec = secs[i % len(secs)]
            if i % 5 == 0:  # the stub fabricates 1 in 5, ground-truth labelled
                if i % 10 == 0:
                    out.append(
                        Claim(
                            section="BNS 420",
                            quote="whoever commits cyber fraud",
                            is_fabricated=True,
                        )
                    )
                else:
                    out.append(
                        Claim(
                            section=sec,
                            quote="the accused clearly intended to defraud the victim",
                            is_fabricated=True,
                        )
                    )
            else:
                out.append(
                    Claim(section=sec, quote=REAL_PHRASES[sec], is_fabricated=False)
                )
        return out
