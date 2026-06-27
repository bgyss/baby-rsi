theorem and_comm_candidate (p q : Prop) : p ∧ q -> q ∧ p := by
  intro h
  constructor
  exact h.right
  exact h.left
