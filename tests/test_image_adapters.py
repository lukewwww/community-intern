import unittest

from community_intern.llm.image_adapters import (
    Base64Image,
    GeminiImageAdapter,
    ImagePart,
    OpenAIImageAdapter,
    QwenImageAdapter,
    TextPart,
)


class ImageAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = Base64Image(
            base64_data="ZGF0YQ==",
            mime_type="image/png",
            source_url="https://example.com/image.png",
            filename="image.png",
        )

    def test_openai_adapter_text_only(self) -> None:
        adapter = OpenAIImageAdapter()
        content = adapter.build_user_content(parts=[TextPart(type="text", text="hello")])
        self.assertEqual(content, "hello")

    def test_openai_adapter_with_image(self) -> None:
        adapter = OpenAIImageAdapter()
        content = adapter.build_user_content(
            parts=[
                TextPart(type="text", text="hello"),
                ImagePart(type="image", image=self.image),
            ]
        )
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[0]["text"], "hello")
        self.assertEqual(content[1]["type"], "image_url")

    def test_gemini_adapter_with_image(self) -> None:
        adapter = GeminiImageAdapter()
        content = adapter.build_user_content(
            parts=[
                TextPart(type="text", text="hello"),
                ImagePart(type="image", image=self.image),
            ]
        )
        self.assertIsInstance(content, list)
        self.assertIn("inline_data", content[1])
        self.assertEqual(content[1]["inline_data"]["mime_type"], "image/png")

    def test_qwen_adapter_with_image(self) -> None:
        adapter = QwenImageAdapter()
        content = adapter.build_user_content(
            parts=[
                ImagePart(type="image", image=self.image),
                TextPart(type="text", text="hello"),
            ]
        )
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "image")
        self.assertEqual(content[-1]["type"], "text")


if __name__ == "__main__":
    unittest.main()
