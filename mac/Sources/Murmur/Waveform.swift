import SwiftUI

/// Mirrored bar waveform that reacts to the current audio level.
///
/// At level=0 the bars collapse to a nearly-flat line (baseline height).
/// At level=1 they swing up to full amplitude following a smoothly animated
/// sum-of-sines pattern. Between, the amplitude scales linearly — so the
/// waveform visibly "wakes up" when the user starts speaking and settles
/// when they pause.
struct Waveform: View {
    /// 0...1, smoothed by the controller.
    var level: Double

    private let barCount = 11
    private let barWidth: CGFloat = 2
    private let spacing: CGFloat = 2.5
    private let baselineHeight: CGFloat = 2
    private let maxHeight: CGFloat = 18

    @State private var phase: Double = 0
    private let timer = Timer.publish(every: 1.0 / 30.0, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: spacing) {
            ForEach(0..<barCount, id: \.self) { i in
                Capsule()
                    .fill(Color(red: 0.94, green: 0.94, blue: 0.94))
                    .frame(width: barWidth, height: height(for: i))
                    .animation(.easeOut(duration: 0.08), value: level)
            }
        }
        .frame(width: CGFloat(barCount) * barWidth + CGFloat(barCount - 1) * spacing)
        .onReceive(timer) { _ in phase += 0.09 }
    }

    private func height(for i: Int) -> CGFloat {
        let center = Double(barCount - 1) / 2.0
        let distFromCenter = abs(Double(i) - center) / center
        let envelope = 1.0 - 0.35 * distFromCenter

        let a = sin(phase * 1.6 + Double(i) * 0.8)
        let b = sin(phase * 2.4 + Double(i) * 1.4)
        let mix = (a + 0.55 * b) / 1.55
        let norm = (mix + 1.0) / 2.0

        // Square-root curve makes quiet speech visibly expressive.
        // Idle bars still breathe subtly so the pill doesn't look frozen.
        let amplitude = 0.12 + 0.88 * sqrt(level)
        let dynamic = norm * envelope * amplitude

        return baselineHeight + CGFloat(dynamic) * (maxHeight - baselineHeight)
    }
}
