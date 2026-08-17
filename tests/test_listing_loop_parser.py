import unittest

from sources import _parse_listing_loop_alert


class ListingLoopParserTests(unittest.TestCase):
    def test_each_property_uses_details_from_its_own_email_card(self):
        html = """
        <table>
          <tr><td class="property-card">
            <h2>12 Ridge Road, Tapitallee NSW 2540</h2>
            <p>$900,000 · 40 acres · 3 Bed · 2 Bath</p>
            <img src="https://images.example/first.jpg">
            <a href="https://buyer.listingloop.com.au/buyer/#/properties/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa">View</a>
          </td></tr>
          <tr><td class="property-card">
            <h2>85 Creek Lane, Braidwood NSW 2622</h2>
            <p>$1,200,000 · 75 acres · 4 Bed · 2 Bath</p>
            <img src="https://images.example/second.jpg">
            <a href="https://buyer.listingloop.com.au/buyer/#/properties/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb">View</a>
          </td></tr>
        </table>
        """

        properties = _parse_listing_loop_alert(html, {})

        self.assertEqual(len(properties), 2)
        self.assertEqual(properties[0]["address"], "12 Ridge Road")
        self.assertEqual(properties[0]["price"], 900_000)
        self.assertEqual(properties[0]["photo_url"], "https://images.example/first.jpg")
        self.assertEqual(properties[1]["address"], "85 Creek Lane")
        self.assertEqual(properties[1]["price"], 1_200_000)
        self.assertEqual(properties[1]["photo_url"], "https://images.example/second.jpg")


if __name__ == "__main__":
    unittest.main()
