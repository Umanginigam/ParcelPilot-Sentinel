from src.llm import StubLLM, Decision


def test_stub_llm_returns_final_answer():
    llm = StubLLM(
        script=[
            Decision(text="Test response")
        ]
    )

    result = llm.decide(
        "system",
        [{"role": "user", "content": "hello"}],
        [],
    )

    assert result.is_final
    assert result.text == "Test response"