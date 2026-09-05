// #popclip
// name: Reverse
// identifier: io.github.jondkinney.omapop.reverse
// description: Reverse the selected text, one action per line count. A module-based extension.
// icon: flip-x R

defineExtension({
  actions: [
    {
      title: "Reverse characters",
      icon: "flip-x R",
      after: "paste-result",
      code(input) {
        return Array.from(input.text).reverse().join("")
      },
    },
    {
      title: "Reverse lines",
      icon: "flip-y R",
      requirements: ["text"],
      regex: /\n/,
      after: "paste-result",
      code(input) {
        return input.text.split("\n").reverse().join("\n")
      },
    },
  ],
})
