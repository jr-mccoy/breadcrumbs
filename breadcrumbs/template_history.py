"""breadcrumbs — the template files crumb-kit has shipped, by content hash.

`crumb init` copies a few explanatory files into a store (`README.md`, and the
READMEs of `generated/`, `index/` and `private/`); until 0.1.7 it also made an
`evidence/refs.yml`. A store keeps whatever version it was created with, so an
upgraded store can tell an agent something that is no longer true: after the
DoWhat migration to schema 4 the store README still said traps live in
`known-traps.md`, which had become a generated index (retest of 0.5.0, item 12).

`crumb migrate` replaces a template file that still matches one of these hashes
(nobody edited it), and leaves an edited one alone with a warning. The hashes
are SHA-256 of the file with CRLF folded to LF, one entry per version ever
committed to the template tree. Regenerate with `python tools/template_hashes.py`
when a template changes; the current template is recognised from the package
itself, so forgetting only means the *previous* version is not upgraded.
"""

from __future__ import annotations

SHIPPED: dict[str, frozenset[str]] = {
    "README.md": frozenset(
        {
            "1082c5872f183d4510173f7b193f444ba90d331072d8617fe7a7a9090b7b6d09",
            "1eb3ae34ffb5842c5f5e5fcd5e30e9995a4c0e08729501ca44c10e03c6ae3893",
            "478b0a5ffcacf3e8e82324892190d84e3cb9fd0caaa75d9fca51de2a8b5f39c5",
            "60eab4da85c7605ea5649ff55272b92a4247184171addd22dccda77931f905eb",
            "6976f0b23b1e049e4589a61a08baa711a2304df54adbebc5ffb28dbe05af0d53",
            "79eb839dc2546ddbbd7f6fae72cf94a5bf9bc41468df6fa201e7df564ebab0e2",
            "8b5f639d295d46d7c09f6e65cd86d7efe945a57a4acaf35bb7e5ef4b4f38c0f8",
            "8ea51e4040590228abb6051a477f6df7a8f7a6db2f92ddc57e8bb2a7cc334dc8",
            "beaf10960dcd40074a0aba11266cb64420d0b75b8fbb2dea40eae04c11912f34",
            "fc2eb17856f910667ca918b12b59c12c419a9815663b0a3c51c425fade65a080",
        }
    ),
    "generated/README.md": frozenset(
        {
            "1f805d58798a37860904f30bc4a6fdc39c40e910912dd6bee95fc852fb4da59c",
            "2188bce97047582adfcb60e0f6e178756740e588ae90946e4bd5023df2918be1",
            "50cd3f52f657f100f06c892854c528d88934ba31e08836598946fafcda718d89",
            "d33860a568879a3ee57ad7d6784645d0ba4244853e644cdad02ba2cc327cad10",
            "ed91fdfb986cedab72ebb82dd919e39d4f9cb971ce65b816caf9a80666eddb4b",
            "f3bd475c300ac540a8d8f22c62173ad69c6e15eac4f05a70fa4594ace2bb39ae",
        }
    ),
    "index/README.md": frozenset(
        {
            "1c48b56ff7a4a203e24e7a13fe5718a060dbfbd811a44eead7368bafaba09930",
            "2f862473ab89c0a71c076b95357e029188c508f765dc1f6be26b8ddccea761cf",
            "8a29d415e81d3069a053b9107a29bfd52f325a34e60f63d1abe2705e4e76e40a",
            "b91fb83f5b244c815c2ad8a1b827d0221e5332141c4b804b3b4f715c380ee906",
        }
    ),
    "private/README.md": frozenset(
        {
            "f9212fbf257ca4a9a5b69a3f0becf0cc23a0ec44c59ca2cfb03f060d3383b344",
            "fe5e83a03d4ed8fda7f5c73ff36c0dc7133b5a81bf7b63e0a530a4846b12a951",
        }
    ),
    "evidence/refs.yml": frozenset(
        {
            "f0120b84eb42146ab3d424961b9cdf971dbb6a2c51a5069d7b6e433fa17a364d",
        }
    ),
}
