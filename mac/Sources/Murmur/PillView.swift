import SwiftUI

private let offWhite = Color(red: 0.94, green: 0.94, blue: 0.94)
private let pillBlack = Color(red: 0.04, green: 0.04, blue: 0.04)

private let pillWidth: CGFloat = 124
private let pillHeight: CGFloat = 26

struct PillView: View {
    @EnvironmentObject var controller: PillController

    @State private var pillScale: CGFloat = 0.4
    @State private var pillOpacity: Double = 0.0

    var body: some View {
        ZStack {
            Color.clear

            RoundedRectangle(cornerRadius: pillHeight / 2)
                .fill(pillBlack)
                .frame(width: pillWidth, height: pillHeight)
                .shadow(color: .black.opacity(0.5), radius: 9, x: 0, y: 4)
                .overlay {
                    content
                        .padding(.horizontal, 8)
                        .frame(width: pillWidth, height: pillHeight)
                }
                .scaleEffect(pillScale)
                .opacity(pillOpacity)
        }
        .onChange(of: controller.state) { newState in
            switch newState {
            case .recording:
                // Reset to small/invisible before animating in
                pillScale = 0.4
                pillOpacity = 0.0
                withAnimation(.spring(response: 0.28, dampingFraction: 0.6)) {
                    pillScale = 1.0
                    pillOpacity = 1.0
                }
            case .done:
                // Zoom out while still showing the three dots
                withAnimation(.easeIn(duration: 0.18)) {
                    pillScale = 0.4
                    pillOpacity = 0.0
                }
            default:
                break
            }
        }
    }

    private var stateKey: Int {
        switch controller.state {
        case .hidden: return 0
        case .recording: return 1
        case .processing: return 2
        case .done: return 3
        case .error: return 4
        }
    }

    @ViewBuilder private var content: some View {
        switch controller.state {
        case .hidden:
            EmptyView()
        case .recording(let since):
            RecordingContent(since: since)
        case .processing:
            ProcessingContent()
        case .done:
            ProcessingContent()
        case .error(let msg):
            Text(msg)
                .font(.system(size: 9))
                .foregroundColor(offWhite)
                .lineLimit(2)
        }
    }
}

private struct RecordingContent: View {
    let since: Date
    @EnvironmentObject var controller: PillController
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(offWhite)
                .frame(width: 5, height: 5)
                .opacity(pulse ? 0.45 : 1.0)
                .animation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true), value: pulse)
                .onAppear { pulse = true }

            Waveform(level: controller.level)
                .frame(maxWidth: .infinity)

            TimelineView(.periodic(from: .now, by: 0.25)) { context in
                let elapsed = max(0, Int(context.date.timeIntervalSince(since)))
                Text(String(format: "%d:%02d", elapsed / 60, elapsed % 60))
                    .font(.system(size: 10, weight: .regular, design: .default))
                    .monospacedDigit()
                    .foregroundColor(offWhite)
            }
        }
    }
}

private struct ProcessingContent: View {
    @State private var animate = false
    private let dotCount = 3

    var body: some View {
        HStack(spacing: 5) {
            ForEach(0..<dotCount, id: \.self) { i in
                Circle()
                    .fill(offWhite)
                    .frame(width: 5, height: 5)
                    .opacity(animate ? 0.25 : 1.0)
                    .animation(
                        .easeInOut(duration: 0.6)
                            .repeatForever(autoreverses: true)
                            .delay(Double(i) * 0.18),
                        value: animate
                    )
            }
        }
        .onAppear { animate = true }
    }
}
