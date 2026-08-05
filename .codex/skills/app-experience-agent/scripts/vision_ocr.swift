import Foundation
import Vision
import ImageIO
import CoreGraphics
import Darwin

guard CommandLine.arguments.count >= 2 else {
    fputs("usage: vision_ocr.swift IMAGE_PATH\n", stderr)
    exit(2)
}

let imagePath = CommandLine.arguments[1]
let imageURL = URL(fileURLWithPath: imagePath)
guard let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
      let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fputs("cannot decode image: \(imagePath)\n", stderr)
    exit(2)
}

let width = Double(image.width)
let height = Double(image.height)
var observationsOutput: [[String: Any]] = []

let request = VNRecognizeTextRequest { request, error in
    if let error = error {
        fputs("Vision OCR failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }

    let observations = (request.results as? [VNRecognizedTextObservation]) ?? []
    for observation in observations {
        guard let candidate = observation.topCandidates(1).first else { continue }
        let box = observation.boundingBox
        let pixelX = box.minX * width
        let pixelY = (1.0 - box.maxY) * height
        observationsOutput.append([
            "text": candidate.string,
            "confidence": Double(candidate.confidence),
            "x": pixelX,
            "y": pixelY,
            "width": box.width * width,
            "height": box.height * height,
            "normalizedX": box.minX,
            "normalizedY": box.minY,
            "normalizedWidth": box.width,
            "normalizedHeight": box.height
        ])
    }
}

request.recognitionLevel = .fast
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = false
request.minimumTextHeight = 0.008

do {
    let handler = VNImageRequestHandler(url: imageURL, options: [:])
    try handler.perform([request])
    let data = try JSONSerialization.data(withJSONObject: observationsOutput, options: [])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
} catch {
    fputs("Vision OCR failed: \(error.localizedDescription)\n", stderr)
    exit(1)
}
