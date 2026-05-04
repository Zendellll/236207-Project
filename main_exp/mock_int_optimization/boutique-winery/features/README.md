### Reasoning Poisoning Experiment Features: Hypotheses & ASR Impact

**1. Length (High vs. Low)**
* **Concept:** Expansive, detailed narratives vs. short, punchy commands.
* **Experimental Rationale:** We aim to measure whether an LLM's attention mechanism is more heavily influenced by a large token footprint or by dense, easily extractable information. 
* **Hypothesis:** We hypothesize that the High Length variant might act as an "attention anchor," increasing ASR by dominating the context window, while the Low Length variant tests if concise commands are preferentially extracted for final recommendations.

**2. Capitalization (All-Caps vs. All Lowercase)**
* **Concept:** Aggressive, capitalized text vs. low-effort, uncapitalized text.
* **Experimental Rationale:** This evaluates how casing affects the model's perception of urgency versus spam. 
* **Hypothesis:** We hypothesize that All-Caps may artificially inflate perceived severity (raising ASR) or conversely trigger spam/hyperbole filters (lowering ASR). The Lowercase variant tests a stealth approach, measuring if mimicking organic, low-effort UGC successfully bypasses these filters while still steering the model.

**3. Confidence (Assertive vs. Hesitant)**
* **Concept:** Absolute, definitive claims vs. subjective qualifiers ("I think," "maybe").
* **Experimental Rationale:** We are testing the LLM's bias toward extracting definitive "facts" over subjective opinions. 
* **Hypothesis:** We anticipate that high confidence will increase ASR by presenting the poisoned claim as ground truth. The hesitant variant tests whether epistemic hedging causes the model to discount the threat, or if the underlying safety concern still triggers an alert.

**4. Evidence (Fabricated Citations vs. Anecdotal)**
* **Concept:** Fake URLs and official report numbers vs. "trust me bro" subjective claims.
* **Experimental Rationale:** This measures the model's alignment heuristics regarding verifiable, authoritative sources. 
* **Hypothesis:** We hypothesize that injecting fabricated citations and URLs creates a "halo effect" of credibility. This could potentially bypass fact-checking guardrails and significantly boost ASR compared to purely anecdotal attacks.

**5. Tone (Explicit/Angry vs. Polite/Implicit)**
* **Concept:** Rude, aggressive language vs. gentle, deferential phrasing.
* **Experimental Rationale:** We seek to evaluate the interaction between sentiment intensity and toxicity filters. 
* **Hypothesis:** Explicit anger might successfully signal extreme danger (raising ASR), or it might cross toxicity thresholds and cause the comment to be ignored. Polite attacks test if a gentle tone can stealthily manipulate the recommendation without tripping any safety alarms.

**6. Language Level (Formal/Academic vs. Informal/Simple)**
* **Concept:** Sophisticated, complex syntax vs. emotional, colloquial slang.
* **Experimental Rationale:** This tests whether the model inherently associates syntactic complexity with reliability. 
* **Hypothesis:** We hypothesize that formal, academic language may yield a higher ASR by mimicking authoritative writing. Conversely, the informal variant tests if raw, panicked emotion is enough to steer the model, or if it gets down-weighted as unreliable noise.

**7. Numerical Density (Stats/Figures vs. Vague)**
* **Concept:** Heavy use of precise speeds, prices, and percentages vs. qualitative descriptors.
* **Experimental Rationale:** We aim to measure the LLM's bias toward quantitative data extraction. 
* **Hypothesis:** A high density of exact figures and statistics is expected to make the fabricated claim appear more grounded and data-driven, potentially increasing the likelihood that the model extracts and repeats it over vague complaints.

**8. Punctuation (Excessive vs. None)**
* **Concept:** Heavy use of exclamation marks and ellipses vs. a total absence of punctuation.
* **Experimental Rationale:** This determines if punctuation serves as a structural urgency multiplier or a spam indicator. 
* **Hypothesis:** Excessive punctuation might spike ASR through perceived severity or tank it via spam filters. Zero punctuation tests how well the attack survives when the model is forced to rely purely on raw semantic proximity without grammatical boundaries.

**9. Repetition (Duplicated vs. Concise)**
* **Concept:** Repeating core claims and target names multiple times vs. stating them exactly once.
* **Experimental Rationale:** This experiment tests the model's response to token redundancy and frequency within a single document. 
* **Hypothesis:** We hypothesize that repeating core claims might artificially inflate their weight, tricking the LLM into perceiving a local "consensus" (raising ASR). Alternatively, it may trigger a redundancy penalty that flags the text as synthetic.

**10. Structure (Highly Formatted vs. Scrambled)**
* **Concept:** Clear Markdown (headers, lists, tables) vs. a messy, non-linear stream of consciousness.
* **Experimental Rationale:** We aim to evaluate the model's reliance on layout markers for information extraction. 
* **Hypothesis:** We hypothesize that highly structured formatting will spoon-feed the poisoned data to the LLM, maximizing ASR. The scrambled variant tests if the raw semantic payload is strong enough to manipulate the model without any structural cues.