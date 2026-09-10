import Foundation
import Vision
import ImageIO
let url = URL(fileURLWithPath: CommandLine.arguments[1])
guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { fatalError("SCREENSHOT_UNREADABLE") }
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
print(text)
guard text.contains("GO"), text.contains("登录"), text.contains("邮箱") || text.contains("密码") else {
    fputs("LOGIN_SCREEN_NOT_RENDERED\n", stderr)
    exit(1)
}
print("LOGIN_SCREEN_RENDERED: PASS")
