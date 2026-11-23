/-
  議事録 自動作成 検証モデル（Lean 4）
  対応文書: 議事録検証計画.md

  目的:
    文字起こしから作った議事録（Claude版 C）が、
    人手の議事録（A版 R）と「同等以上」かを、
    同じ正解データ・同じ判定関数で機械的に判定する。

  前提:
    ・正解データ（発言セグメント一覧・キーポイント一覧）は人が作る。
      このモデルは「判定の一貫性」を保証するが、
      「正解データの正しさ」は保証しない。
    ・議事録の各記載項目は、評価者が根拠となる発言セグメントIDにひも付ける。
-/

namespace MinutesVerification

/-! ## 1. 基本の型 -/

/-- 発言者 -/
inductive Speaker where
  | personF | personT | personI | personAI | personA
  deriving DecidableEq, Repr

/-- 発言の確度。
  弱い順に 推測 < 伝聞 < 本人認識 < 確認済み。
  （伝聞と本人認識は本来比較しにくいが、ここでは単純化して全順序とする） -/
inductive Certainty where
  | guess       -- 推測（「多分」「〜と思う」）
  | hearsay     -- 伝聞（「〜と聞いている」）
  | belief      -- 本人認識（「〜という認識」）
  | confirmed   -- 確認済みの事実
  deriving DecidableEq, Repr

def Certainty.rank : Certainty → Nat
  | .guess     => 0
  | .hearsay   => 1
  | .belief    => 2
  | .confirmed => 3

abbrev ClaimId   := Nat   -- 主張（内容）のID。キーポイントもこのIDで表す
abbrev SegmentId := Nat   -- 文字起こし上の発言セグメントのID

/-- 正解データ側：文字起こしの発言セグメント（評価者が注釈） -/
structure Segment where
  id        : SegmentId
  speaker   : Speaker
  claim     : ClaimId
  certainty : Certainty
  garbled   : Bool        -- 誤変換・聞き取り不良で内容が推定になる箇所
  deriving Repr

/-- 議事録側：記載された1項目（評価者が根拠セグメントをひも付け） -/
structure Item where
  claim          : ClaimId
  speaker        : Speaker
  certainty      : Certainty     -- 記載上の確度（語尾から判定）
  support        : List SegmentId
  markedInferred : Bool          -- 【推定】【聞き取り不明】等の明示があるか
  deriving Repr

abbrev Transcript := List Segment
abbrev Minutes    := List Item

/-! ## 2. 項目ごとの判定 -/

/-- 項目の根拠になる発言セグメント（ID一致かつ内容一致） -/
def supportingSegments (t : Transcript) (i : Item) : List Segment :=
  t.filter (fun s => i.support.contains s.id && decide (s.claim = i.claim))

/-- 根拠あり -/
def isSupported (t : Transcript) (i : Item) : Bool :=
  !(supportingSegments t i).isEmpty

/-- 付け足し：発言に根拠がない記載 -/
def isFabricated (t : Transcript) (i : Item) : Bool :=
  !isSupported t i

/-- 話者誤り：根拠はあるが、記載の発言者が根拠のどの発言者とも一致しない -/
def hasSpeakerError (t : Transcript) (i : Item) : Bool :=
  isSupported t i &&
  !(supportingSegments t i).any (fun s => decide (s.speaker = i.speaker))

/-- 確度の格上げ：発言より強い確度で書いた（例：「多分」を断定に） -/
def isOverclaim (t : Transcript) (i : Item) : Bool :=
  isSupported t i &&
  (supportingSegments t i).all (fun s => decide (s.certainty.rank < i.certainty.rank))

/-- 確度の格下げ（参考指標。合否には使わない） -/
def isUnderclaim (t : Transcript) (i : Item) : Bool :=
  isSupported t i &&
  (supportingSegments t i).all (fun s => decide (i.certainty.rank < s.certainty.rank))

/-- 無断推定：根拠が誤変換箇所のみなのに【推定】等の明示がない -/
def isUnflaggedGarbled (t : Transcript) (i : Item) : Bool :=
  isSupported t i &&
  (supportingSegments t i).all (·.garbled) &&
  !i.markedInferred

/-- キーポイント k を、根拠つきで記載しているか -/
def covers (t : Transcript) (m : Minutes) (k : ClaimId) : Bool :=
  m.any (fun i => decide (i.claim = k) && isSupported t i)

/-! ## 3. 議事録全体の評価 -/

def countIf (p : Item → Bool) (m : Minutes) : Nat :=
  (m.filter p).length

structure Report where
  fabricated       : Nat   -- 付け足し
  overclaim        : Nat   -- 確度の格上げ
  speakerError     : Nat   -- 話者誤り
  unflaggedGarbled : Nat   -- 無断推定
  underclaim       : Nat   -- 確度の格下げ（参考）
  covered          : Nat   -- 網羅できたキーポイント数
  keyCount         : Nat   -- キーポイント総数
  deriving Repr, DecidableEq

def evaluate (t : Transcript) (keys : List ClaimId) (m : Minutes) : Report :=
  { fabricated       := countIf (isFabricated t) m
    overclaim        := countIf (isOverclaim t) m
    speakerError     := countIf (hasSpeakerError t) m
    unflaggedGarbled := countIf (isUnflaggedGarbled t) m
    underclaim       := countIf (isUnderclaim t) m
    covered          := (keys.filter (covers t m)).length
    keyCount         := keys.length }

/-- 合格基準（C が R と「同等以上」）
  1. C の付け足し = 0
  2. C の確度の格上げ = 0
  3. C の無断推定 = 0
  4. C の話者誤り ≤ R の話者誤り
  5. C の網羅数 ≥ R の網羅数 -/
def passes (c r : Report) : Bool :=
  decide (c.fabricated = 0) &&
  decide (c.overclaim = 0) &&
  decide (c.unflaggedGarbled = 0) &&
  decide (c.speakerError ≤ r.speakerError) &&
  decide (r.covered ≤ c.covered)

/-- 検証全体：同じ正解データ・同じ関数で C と R を評価して比べる -/
def verify (t : Transcript) (keys : List ClaimId) (c r : Minutes) : Bool :=
  passes (evaluate t keys c) (evaluate t keys r)

/-! ## 4. 性質の証明 -/

/-- 付け足しが1件でもあれば、他がどれだけ良くても不合格 -/
theorem fabrication_fails (c r : Report) (h : c.fabricated ≠ 0) :
    passes c r = false := by
  simp [passes, h]

/-- 確度の格上げが1件でもあれば不合格 -/
theorem overclaim_fails (c r : Report) (h : c.overclaim ≠ 0) :
    passes c r = false := by
  simp [passes, h]

/-- 網羅数が R を下回れば不合格 -/
theorem coverage_shortfall_fails (c r : Report) (h : c.covered < r.covered) :
    passes c r = false := by
  have : ¬ r.covered ≤ c.covered := Nat.not_le.mpr h
  simp [passes, this]

/-- 全項目に根拠があれば、付け足しは 0 件 -/
theorem no_fabrication_of_all_supported
    (t : Transcript) (keys : List ClaimId) (m : Minutes)
    (h : ∀ i ∈ m, isSupported t i = true) :
    (evaluate t keys m).fabricated = 0 := by
  simp only [evaluate, countIf, List.length_eq_zero]
  apply List.filter_eq_nil_iff.mpr
  intro i hi
  simp [isFabricated, h i hi]

/-- 記載の確度を発言と同じにしていれば、その項目は格上げにならない -/
theorem same_certainty_not_overclaim
    (t : Transcript) (i : Item)
    (h : ∀ s ∈ supportingSegments t i, s.certainty = i.certainty) :
    isOverclaim t i = false := by
  unfold isOverclaim
  cases hs : isSupported t i with
  | false => rfl
  | true =>
    simp only [Bool.true_and]
    have hne : supportingSegments t i ≠ [] := by
      intro he
      simp [isSupported, he] at hs
    obtain ⟨s, hsmem⟩ := List.exists_mem_of_ne_nil _ hne
    apply Bool.eq_false_iff.mpr
    intro hall
    have hlt := (List.all_eq_true.mp hall) s hsmem
    rw [h s hsmem] at hlt
    simp at hlt

/-! ## 5. 例：10/30 ヒアリングの一部で動作確認（値は説明用の仮データ） -/

/-
  セグメント（正解データの例）
   1: F   推測     #1 検収TはMデータとHデータの差異で違算を検出
   2: T 本人認識 #2 MDBは2020年以降更新されていない
   3: T 確認済み #3 特値違算シートの提出期限が月内に前倒し
   4: I 本人認識 #4 BPRは部署2の活動と合わせる必要
   5: F   確認済み #5 HデータはHATLiの発注データ（誤変換あり）
  キーポイント: #1〜#5
-/
def sampleTranscript : Transcript :=
  [ ⟨1, .personF,    1, .guess,     false⟩,
    ⟨2, .personT, 2, .belief,    false⟩,
    ⟨3, .personT, 3, .confirmed, false⟩,
    ⟨4, .personI,      4, .belief,    false⟩,
    ⟨5, .personF,    5, .confirmed, true⟩ ]

def sampleKeys : List ClaimId := [1, 2, 3, 4, 5]

/-- 人手版の例：#1 を断定で記載（格上げ）、#4 は未記載 -/
def sampleR : Minutes :=
  [ ⟨1, .personF,    .confirmed, [1], false⟩,
    ⟨2, .personT, .belief,    [2], false⟩,
    ⟨3, .personT, .confirmed, [3], false⟩,
    ⟨5, .personF,    .confirmed, [5], false⟩ ]

/-- 自動版の良い例：確度を保持、誤変換箇所に【推定】、全キーを網羅 -/
def sampleC_good : Minutes :=
  [ ⟨1, .personF,    .guess,     [1], false⟩,
    ⟨2, .personT, .belief,    [2], false⟩,
    ⟨3, .personT, .confirmed, [3], false⟩,
    ⟨4, .personI,      .belief,    [4], false⟩,
    ⟨5, .personF,    .confirmed, [5], true⟩ ]

/-- 自動版の悪い例：根拠のない項目（#9）を付け足した -/
def sampleC_bad : Minutes :=
  sampleC_good ++ [ ⟨9, .personT, .confirmed, [], false⟩ ]

#eval evaluate sampleTranscript sampleKeys sampleR
#eval evaluate sampleTranscript sampleKeys sampleC_good
#eval evaluate sampleTranscript sampleKeys sampleC_bad

example : verify sampleTranscript sampleKeys sampleC_good sampleR = true  := by decide
example : verify sampleTranscript sampleKeys sampleC_bad  sampleR = false := by decide

end MinutesVerification
