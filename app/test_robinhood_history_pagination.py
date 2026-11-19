"""Full Robinhood history >50 pages must reconcile, with strict upper bound."""
import unittest
from unittest.mock import patch
from robinhood_crypto_gateway import RobinhoodCryptoAdapter,RobinhoodUnavailable

class OrderHistoryPaginationTests(unittest.TestCase):
 def test_orders_page_51_plus_is_not_mistaken_for_broker_failure(self):
  obj=object.__new__(RobinhoodCryptoAdapter)
  count=[0]
  def page(path,params):
   self.assertEqual(path,"/api/v2/crypto/trading/orders/")
   n=int(params.get("cursor","0"))
   count[0]+=1
   next_url=("https://trading.robinhood.com/api/v2/crypto/trading/orders/?cursor="+str(n+1)
             if n<54 else None)
   return {"results":[{"id":str(n)}],"next":next_url}
  with patch.object(obj,"balances",return_value={"account_number":"a"}),patch.object(obj,"_get",side_effect=page):
   orders=obj.orders("a")
  self.assertEqual(len(orders),55)
  self.assertEqual(count[0],55)
  self.assertEqual(orders[-1]["id"],"54")

 def test_history_beyond_250_pages_is_never_returned_partial(self):
  obj=object.__new__(RobinhoodCryptoAdapter)
  def page(path,params):
   n=int(params.get("cursor","0"))
   return {"results":[{"id":str(n)}],
           "next":"https://trading.robinhood.com/api/v2/crypto/trading/orders/?cursor="+str(n+1)}
  with patch.object(obj,"balances",return_value={"account_number":"a"}),patch.object(obj,"_get",side_effect=page):
   with self.assertRaisesRegex(RobinhoodUnavailable,"Pagination limit"):
    obj.orders("a")

 def test_generic_pagination_ceiling_does_not_expand(self):
  obj=object.__new__(RobinhoodCryptoAdapter)
  def page(path,params):
   n=int(params.get("cursor","0"))
   return {"results":[{"id":str(n)}],
           "next":"https://trading.robinhood.com/api/v2/crypto/trading/trading_pairs/?cursor="+str(n+1)}
  with patch.object(obj,"_get",side_effect=page):
   with self.assertRaisesRegex(RobinhoodUnavailable,"Pagination limit"):
    obj.trading_pairs()

if __name__=="__main__":unittest.main()
