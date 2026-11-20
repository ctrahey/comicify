Feature: Storytelling to Comics
  As a Product Developer
  I can describe my comic story in natural language and generate a modifiable comic artifact
  So that I can iterate on product features with my team in an interactive and efficient way!

  Note: this file is meta-gherkin! It is not yet "specification by example" and is just meant as a guid to LLM-assisted product development OF this comic system, to paint the broad picture of the feature set.

  Scenario: Prompting & Initial Clarifications
    Given I have written a free-form prompt.md file describing my vision for the comic
    When I run `comicify author path/to/prompt.md`
    Then I should see a question posed to me that clarifies something about my prompt
    And I should see a cursor to compose a response
    When I answer and submit my response
    And complete this a few times as needed by the program
    Then I should see a progress meter while the program works on the structured representation
    And I should then see "complete! review the artifacts in path/to/structured/"
    And I should find a set of structured YAML or JSON files there which include my characteres, story, etc...

  Scenario: Rendering a comic
    Given I have run through the scenario "Prompting & Initial Clarifications"
    When I run `comicify render path/to/prompt.md`
    Then I should see a status progress meter
    And then I should see "complete! find your comic in path/to/rendered/v1"
    And I should find SVG, PNG, or PDF files there with my comic, complete and visual and beautiful and according to my prompts!
